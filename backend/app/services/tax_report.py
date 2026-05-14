"""Налоговый отчёт по WB — воспроизводит методику клиентского бухгалтера 1:1.

В отличие от управленческого P&L (services/pnl_builder.py), здесь применяется
**кассовый метод** учёта по требованиям УСН/АУСН РФ:

- ДОХОД признаётся по дате отчёта WB (`report_date_to`) или по дате
  поступления денег на расчётный счёт (для выкупов / взаимозачётов).
- РАСХОД признаётся только при наличии УПД (универсального передаточного
  документа). У нас нет точной даты УПД через API, поэтому используем
  `rr_dt` как proxy (дата строки в финансовом отчёте близка к дате УПД).
- СЕБЕСТОИМОСТЬ — отдельная статья, вне WB-отчёта (учитывается в 1С через
  скользящую среднюю по оплаченным поставщикам товарам).

Структура отчёта повторяет xlsx-разбивку бухгалтера:

  Доход:
    1. Стоимость реализованного товара и услуг = sum(retail_amount net)
    2. Уведомления о выкупе                    = wb_buyback_notification (ручной ввод)
    3. Взаимозачёты на сумму УПД               = wb_offset_entry (ручной ввод)
    4. Компенсация ущерба                      = supplier_oper_name = «Компенсация ущерба»

  Расход (при наличии УПД):
    2.1 Вознаграждение WB без НДС              = ppvz_vw net
    2.2 НДС с вознаграждения                   = ppvz_vw_nds net
    2.6 Сумма за обеспечение платежа           = acquiring_fee net
    2.7 Логистика                              = delivery_rub
    2.8 Платная приёмка                        = paid_acceptance
    2.9 Штрафы                                 = penalty
    2.10 Прочие удержания                      = deduction
    Хранение                                   = storage_fee
    Возмещение издержек по перевозке           = rebill_logistic_cost

  Себестоимость: from products.cost timeline (тот же что в pnl_builder)

  Налоговая база = Доход − Расход − Себестоимость
  Налог = max(база × ставка, доход × min_ставка)   для УСН-15%/АУСН-20%

Спецификация — xlsx «Расчёт налога на примере Отчёта о реализации» 2026-05-14.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbRedeemNotification, WbReportDetail
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
)
from app.services.pnl_builder import (
    DEFAULT_MIN_TAX_RATE,
    DEFAULT_TAX_RATE,
    _compute_tax_for_fns,
    build_cogs_lookup,
    cost_for_date,
)
from app.services.settings_timeline import load_timeline, value_for_date


@dataclass
class TaxReportRow:
    """Один WB-отчёт реализации = одна строка в налоговой выгрузке."""
    realization_id: int
    report_date_from: date
    report_date_to: date  # дата признания дохода
    # Доход
    income_realization: float = 0.0       # 1. Стоимость реализации (retail_amt net)
    income_compensation: float = 0.0      # 4. Компенсация ущерба
    income_buyback: float = 0.0           # из wb_buyback_notification (ручной)
    income_offset: float = 0.0            # взаимозачёты (ручной)
    income_total: float = 0.0
    # Расход (только UDP-доступные)
    expense_ppvz_vw: float = 0.0          # 2.1 Вознаграждение WB без НДС
    expense_ppvz_vw_nds: float = 0.0      # 2.2 НДС с вознаграждения
    expense_acquiring: float = 0.0        # 2.6 За обеспечение платежа
    expense_delivery: float = 0.0         # 2.7 Логистика
    expense_paid_acceptance: float = 0.0  # 2.8 Платная приёмка
    expense_penalty: float = 0.0          # 2.9 Штрафы
    expense_deduction: float = 0.0        # 2.10 Прочие удержания
    expense_storage: float = 0.0          # Хранение
    expense_rebill_logistic: float = 0.0  # Возмещение перевозки
    expense_total: float = 0.0
    # Себестоимость
    cogs: float = 0.0
    # Налог
    tax_base: float = 0.0
    tax_system: str = ""
    tax_rate: float = 0.0
    tax: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


async def build_tax_report(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    brands: set[str] | None = None,
    cogs_method: str = "historical",
) -> dict[str, Any]:
    """Сгруппированный по WB-отчётам налоговый расчёт за период.

    `date_from`/`date_to` фильтруют по `report_date_to` (дате признания
    дохода). Каждый отчёт реализации становится отдельной строкой.

    `brands` — фильтр для manager-роли (как в build_pnl).

    `cogs_method`:
        - "historical" (default) — Cogs.cost на дату продажи (FIFO замена).
        - "weighted_avg" — средневзвешенная по таблице supplies (1С метод):
          avg_cost(nm) = Σ(qty×cost) / Σ(qty) по paid поставкам до конца
          периода. Для УСН-расхода учитываются только оплаченные поставки.
    """
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    is_compensation_damage = WbReportDetail.supplier_oper_name == "Компенсация ущерба"

    rd_stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
            # === ДОХОД ===
            (
                func.sum(case((OP_SALE, WbReportDetail.retail_amount), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.retail_amount), else_=0))
            ).label("income_realization"),
            func.sum(
                case((is_compensation_damage, REVENUE_FIELD), else_=0)
            ).label("income_compensation"),
            # === РАСХОД (по УПД, только net Продажа − Возврат для ppvz) ===
            (
                func.sum(case((OP_SALE, WbReportDetail.ppvz_vw), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.ppvz_vw), else_=0))
            ).label("expense_ppvz_vw"),
            (
                func.sum(case((OP_SALE, WbReportDetail.ppvz_vw_nds), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.ppvz_vw_nds), else_=0))
            ).label("expense_ppvz_vw_nds"),
            (
                func.sum(case((OP_SALE, WbReportDetail.acquiring_fee), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.acquiring_fee), else_=0))
            ).label("expense_acquiring"),
            func.sum(WbReportDetail.delivery_rub).label("expense_delivery"),
            func.sum(func.coalesce(WbReportDetail.paid_acceptance, 0)).label("expense_paid_acceptance"),
            func.sum(WbReportDetail.penalty).label("expense_penalty"),
            func.sum(WbReportDetail.deduction).label("expense_deduction"),
            func.sum(WbReportDetail.storage_fee).label("expense_storage"),
            func.sum(func.coalesce(WbReportDetail.rebill_logistic_cost, 0)).label("expense_rebill_logistic"),
            # Кол-во проданных штук для COGS
            (
                func.sum(case((OP_SALE, WbReportDetail.quantity), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.quantity), else_=0))
            ).label("units_net"),
        )
        .where(WbReportDetail.realization_id.is_not(None))
        .where(WbReportDetail.report_date_from.is_not(None))
        .where(WbReportDetail.report_date_to.is_not(None))
        .where(WbReportDetail.report_date_to >= date_from)
        .where(WbReportDetail.report_date_to <= date_to)
        .group_by(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
        )
        .order_by(WbReportDetail.report_date_to.desc())
    )
    if nm_filter is not None:
        rd_stmt = rd_stmt.where(WbReportDetail.nm_id.in_(nm_filter))

    rows = (await session.execute(rd_stmt)).all()

    # ── Buybacks (Уведомления о выкупе) — приходят отдельно через Documents API.
    # Группируем по неделе [report_date_from..report_date_to] чтобы попасть в
    # соответствующую строку отчёта. Если выкуп вне границы отчётов — добавим
    # как отдельную строку с realization_id=None ниже.
    buyback_stmt = (
        select(
            WbRedeemNotification.notification_number,
            WbRedeemNotification.notification_date,
            WbRedeemNotification.total_sum_with_vat,
        )
        .where(WbRedeemNotification.notification_date >= date_from)
        .where(WbRedeemNotification.notification_date <= date_to)
        .order_by(WbRedeemNotification.notification_date)
    )
    buyback_rows = (await session.execute(buyback_stmt)).all()
    # Распределяем по периодам [report_date_from..report_date_to]
    buyback_by_realization: dict[int, float] = {}
    unallocated_buybacks: list[dict[str, Any]] = []
    for br in buyback_rows:
        matched = False
        for r in rows:
            if r.report_date_from <= br.notification_date <= r.report_date_to:
                buyback_by_realization[int(r.realization_id)] = (
                    buyback_by_realization.get(int(r.realization_id), 0.0)
                    + float(br.total_sum_with_vat or 0)
                )
                matched = True
                break
        if not matched:
            # Выкуп вне границ отчётов реализации — отдельной строкой
            unallocated_buybacks.append({
                "number": br.notification_number,
                "date": br.notification_date,
                "sum": float(br.total_sum_with_vat or 0),
            })

    # COGS per realization: суммируем стоимость проданных единиц по дате
    # признания дохода (report_date_to). Используем тот же lookup что pnl_builder.
    cogs_lookup = await build_cogs_lookup(session)

    # Per-realization COGS считаем как sum(cost) по фактическим продажам в этом отчёте
    cogs_stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.nm_id,
            WbReportDetail.sale_dt,
            (
                func.sum(case((OP_SALE, WbReportDetail.quantity), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.quantity), else_=0))
            ).label("units_net"),
        )
        .where(WbReportDetail.realization_id.is_not(None))
        .where(WbReportDetail.report_date_to >= date_from)
        .where(WbReportDetail.report_date_to <= date_to)
        .where(WbReportDetail.nm_id.is_not(None))
        .group_by(WbReportDetail.realization_id, WbReportDetail.nm_id, WbReportDetail.sale_dt)
    )
    if nm_filter is not None:
        cogs_stmt = cogs_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    cogs_rows = (await session.execute(cogs_stmt)).all()

    # Weighted-avg lookup — заранее посчитан avg_cost per nm_id для всего
    # периода (paid supplies до date_to). Используется если cogs_method='weighted_avg'.
    weighted_avg_by_nm: dict[int, dict[str, float]] = {}
    if cogs_method == "weighted_avg":
        from app.services.cogs_weighted import compute_weighted_avg_cogs  # noqa: WPS433
        nm_ids_in_period = {int(cr.nm_id) for cr in cogs_rows if cr.nm_id is not None}
        weighted_avg_by_nm = await compute_weighted_avg_cogs(
            session, nm_ids_in_period, period_end=date_to, paid_only=True
        )

    cogs_by_realization: dict[int, float] = {}
    for cr in cogs_rows:
        if cr.units_net <= 0 or cr.nm_id is None:
            continue
        sale_d = cr.sale_dt.date() if cr.sale_dt else None
        if sale_d is None:
            continue
        nm = int(cr.nm_id)
        unit_cost: float | None = None
        if cogs_method == "weighted_avg":
            wa = weighted_avg_by_nm.get(nm)
            if wa and wa["avg_cost"] > 0:
                unit_cost = wa["avg_cost"]
        # Fallback на historical для weighted_avg тоже — иначе теряем COGS
        # на SKU без записей в supplies.
        if unit_cost is None or unit_cost <= 0:
            unit_cost = cost_for_date(cogs_lookup, nm, sale_d)
        if unit_cost is None or unit_cost <= 0:
            continue
        cogs_by_realization[int(cr.realization_id)] = (
            cogs_by_realization.get(int(cr.realization_id), 0.0)
            + unit_cost * float(cr.units_net)
        )

    # Settings timeline (tax_rate, tax_system per date)
    from app.services.pnl_builder import _settings  # noqa: WPS433
    cfg = await _settings(session)
    timeline = await load_timeline(session)

    def _tax_params_for(d: date) -> tuple[str, float, float, bool]:
        ts = value_for_date(timeline, cfg, "tax_system", d) or "none"
        if ts not in DEFAULT_TAX_RATE:
            ts = "none"
        tr = float(value_for_date(timeline, cfg, "tax_rate", d) or DEFAULT_TAX_RATE[ts])
        tmr = float(value_for_date(timeline, cfg, "tax_min_rate", d) or DEFAULT_MIN_TAX_RATE.get(ts, 0.0))
        ri = (value_for_date(timeline, cfg, "reduce_by_insurance", d) or "0") == "1"
        return ts, tr, tmr, ri

    out_rows: list[TaxReportRow] = []
    for r in rows:
        income_realization = float(r.income_realization or 0)
        income_compensation = float(r.income_compensation or 0)
        # Buyback из синхронизированных Уведомлений о выкупе (Documents API).
        # Если notification_date попала в [report_date_from, report_date_to] —
        # добавляем в эту строку отчёта. Взаимозачёты пока не подключены
        # (отдельный документ «Акт взаимозачёта», категория actprofit).
        income_buyback = buyback_by_realization.get(int(r.realization_id), 0.0)
        income_offset = 0.0
        income_total = income_realization + income_compensation + income_buyback + income_offset

        e_ppvz_vw = float(r.expense_ppvz_vw or 0)
        e_ppvz_vw_nds = float(r.expense_ppvz_vw_nds or 0)
        e_acquiring = float(r.expense_acquiring or 0)
        e_delivery = float(r.expense_delivery or 0)
        e_paid_accept = float(r.expense_paid_acceptance or 0)
        e_penalty = float(r.expense_penalty or 0)
        e_deduction = float(r.expense_deduction or 0)
        e_storage = float(r.expense_storage or 0)
        e_rebill = float(r.expense_rebill_logistic or 0)
        expense_total = (
            e_ppvz_vw + e_ppvz_vw_nds + e_acquiring + e_delivery + e_paid_accept
            + e_penalty + e_deduction + e_storage + e_rebill
        )

        cogs = cogs_by_realization.get(int(r.realization_id), 0.0)
        tax_base = max(0.0, income_total - expense_total - cogs)
        ts, tr, tmr, ri = _tax_params_for(r.report_date_to)
        tax = _compute_tax_for_fns(
            ts,
            retail_amt_net=income_total,
            ppvz_vw_net=e_ppvz_vw,
            ppvz_vw_nds_net=e_ppvz_vw_nds,
            delivery=e_delivery,
            paid_acceptance=e_paid_accept,
            penalty=e_penalty,
            deduction=e_deduction,
            storage=e_storage,
            cogs=cogs,
            tax_rate=tr,
            tax_min_rate=tmr,
            reduce_by_insurance=ri,
        )

        out_rows.append(TaxReportRow(
            realization_id=int(r.realization_id),
            report_date_from=r.report_date_from,
            report_date_to=r.report_date_to,
            income_realization=income_realization,
            income_compensation=income_compensation,
            income_buyback=income_buyback,
            income_offset=income_offset,
            income_total=income_total,
            expense_ppvz_vw=e_ppvz_vw,
            expense_ppvz_vw_nds=e_ppvz_vw_nds,
            expense_acquiring=e_acquiring,
            expense_delivery=e_delivery,
            expense_paid_acceptance=e_paid_accept,
            expense_penalty=e_penalty,
            expense_deduction=e_deduction,
            expense_storage=e_storage,
            expense_rebill_logistic=e_rebill,
            expense_total=expense_total,
            cogs=cogs,
            tax_base=tax_base,
            tax_system=ts,
            tax_rate=tr,
            tax=tax,
        ))

    totals = {
        "income_total": round(sum(r.income_total for r in out_rows), 2),
        "expense_total": round(sum(r.expense_total for r in out_rows), 2),
        "cogs": round(sum(r.cogs for r in out_rows), 2),
        "tax_base": round(sum(r.tax_base for r in out_rows), 2),
        "tax": round(sum(r.tax for r in out_rows), 2),
        "income_realization": round(sum(r.income_realization for r in out_rows), 2),
        "expense_ppvz_vw": round(sum(r.expense_ppvz_vw for r in out_rows), 2),
        "expense_ppvz_vw_nds": round(sum(r.expense_ppvz_vw_nds for r in out_rows), 2),
        "expense_delivery": round(sum(r.expense_delivery for r in out_rows), 2),
        "expense_paid_acceptance": round(sum(r.expense_paid_acceptance for r in out_rows), 2),
        "expense_penalty": round(sum(r.expense_penalty for r in out_rows), 2),
        "expense_deduction": round(sum(r.expense_deduction for r in out_rows), 2),
        "expense_storage": round(sum(r.expense_storage for r in out_rows), 2),
        "expense_rebill_logistic": round(sum(r.expense_rebill_logistic for r in out_rows), 2),
        "expense_acquiring": round(sum(r.expense_acquiring for r in out_rows), 2),
    }

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "rows": [r.to_dict() for r in out_rows],
        "totals": totals,
    }
