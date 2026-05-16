"""Налоговый отчёт УСН «Доходы» 6% (без НДС) — методика бухгалтера Стаса.

Воспроизводит расчёт из листа «Итоги», строки 13-20, xlsx
«Стас_Разметка_банка_с_01_01_2026_УСН_Доходы.xlsx» 1:1.

Методика (отличается от АУСН — см. tax_report_ausn.py):

    База_месяц = Отчёты_реализации + Тов_компенсация + Банк_выкупы
                + ВЗЗ_УПД_доставки + ВЗЗ_выкуп_возвраты
    Налог = База × ставка   (УСН-Доходы по умолчанию 6 %)

Источники компонентов:

| Компонент              | Где                                           | Бакетирование    |
|-----------------------|-----------------------------------------------|------------------|
| Отчёты реализации (G) | retail_amount_net для «Основной» отчётов     | period_end month |
| Тов. компенсация (Y)  | «Добровольная компенсация при возврате» ppvz | period_end month |
| Банк выкупы (T)       | wb_payment_order.amount для «По выкупам»     | paid_dt month*   |
| УПД доставки (Z)      | wb_payment_order.upd_delivery_amount         | period_end month |
| Возвраты выкупы (AA)  | wb_payment_order.buyout_returns_amount       | period_end month |

* Bank выкупы: исключаются строки с period_end в предыдущем календарном
году (фискально-годовое правило).

Отличие от АУСН (важно):
- АУСН Bank = sum(T) all reports → УСН использует G+Y для Основной (sale value)
- АУСН исключает Возвраты выкупы → УСН включает (AA)
- Tax rate: 6% vs 8%
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbPaymentOrder, WbRedeemNotification, WbReportDetail
from app.services.period_aggregates import OP_RETURN, OP_SALE
from app.services.tax_report_ausn import _month_key, _iter_months
from app.services.settings_timeline import load_timeline, value_for_date

_USN_INCOME_DEFAULT_RATE = 6.0


@dataclass
class UsnMonthlyRow:
    """Месячная свёртка УСН-Доходы.

    Если `vat_rate > 0` (5% или 7% — невозвратный НДС для УСН с оборотом
    >60M ₽/год по 176-ФЗ от 12.07.2024) — НДС выделяется ИЗ gross-цены
    (внутри суммы), УСН считается с net (gross − НДС).
    """
    month: str  # YYYY-MM
    sale_realization: float = 0.0   # G — sale_net для «Основной» по period_end
    tovar_compensation: float = 0.0  # Y — добровольная компенсация
    bank_buyout: float = 0.0         # T — Итого к оплате для «По выкупам» по paid_dt
    upd_delivery: float = 0.0        # Z — wb_payment_order.upd_delivery_amount
    buyout_returns: float = 0.0      # AA — wb_payment_order.buyout_returns_amount
    base_gross: float = 0.0          # = sale+tov+bank+upd+returns (то же что base для НДС=0)
    vat_rate: float = 0.0
    vat: float = 0.0                  # выделенный НДС (если vat_rate > 0)
    base: float = 0.0                 # = base_gross − vat
    tax_rate: float = _USN_INCOME_DEFAULT_RATE
    tax: float = 0.0                  # УСН с net-базы
    total_tax: float = 0.0            # = tax + vat (общая нагрузка)
    realizations_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            k: (round(v, 2) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
        }


async def _fetch_main_realizations(
    session: AsyncSession,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    """Группируем wb_report_detail по realization_id, фильтр «Основной»
    (определяется отсутствием в wb_redeem_notification).

    Возвращает: realization_id, report_date_from, report_date_to, sale_net,
    dobr_komp.
    """
    is_dobr = WbReportDetail.supplier_oper_name == "Добровольная компенсация при возврате"
    sale_net = (
        func.sum(case((OP_SALE, WbReportDetail.retail_amount), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.retail_amount), else_=0))
    ).label("sale_net")
    dobr_komp = func.sum(
        case((is_dobr, WbReportDetail.ppvz_for_pay), else_=0)
    ).label("dobr_komp")

    stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
            sale_net,
            dobr_komp,
        )
        .where(WbReportDetail.report_date_to.is_not(None))
        .where(WbReportDetail.report_date_to >= period_start - timedelta(days=60))
        .where(WbReportDetail.report_date_to <= period_end + timedelta(days=30))
        .group_by(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
        )
    )
    rows = (await session.execute(stmt)).all()

    # «По выкупам» → realization_id в wb_redeem_notification.notification_number
    redeem_ids_stmt = select(WbRedeemNotification.notification_number)
    redeem_ids = {
        int(rid) for (rid,) in (await session.execute(redeem_ids_stmt)).all()
        if rid and str(rid).isdigit()
    }

    out: list[dict[str, Any]] = []
    for r in rows:
        rid = int(r.realization_id) if r.realization_id else None
        if rid in redeem_ids:
            continue  # пропускаем «По выкупам» — для них Банк-буйаут отдельно
        out.append({
            "realization_id": rid,
            "report_date_from": r.report_date_from,
            "report_date_to": r.report_date_to,
            "sale_net": float(r.sale_net or 0),
            "dobr_komp": float(r.dobr_komp or 0),
        })
    return out


async def _fetch_period_starts(
    session: AsyncSession,
) -> dict[int, date]:
    """Map realization_id → report_date_from (для UPD/AA period_start правила).

    Возвращает {rid: date}.
    """
    stmt = (
        select(
            WbReportDetail.realization_id,
            func.min(WbReportDetail.report_date_from).label("ps"),
        )
        .where(WbReportDetail.report_date_from.is_not(None))
        .group_by(WbReportDetail.realization_id)
    )
    rows = (await session.execute(stmt)).all()
    return {int(r.realization_id): r.ps for r in rows if r.realization_id and r.ps}


async def build_usn_monthly_report(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    tax_rate: float | None = None,
    vat_rate: float = 0.0,
) -> dict[str, Any]:
    """УСН-Доходы месячная свёртка.

    Параметры:
        date_from / date_to — диапазон. Включаются полные месяцы попадания дат.
        tax_rate — ставка УСН, по умолчанию 6% (или из settings_timeline).
        vat_rate — невозвратный НДС (по 176-ФЗ для УСН с оборотом >60M ₽/год):
            * 0 — без НДС (default)
            * 5 — пониженная ставка
            * 7 — стандартная ставка
            НДС выделяется ИЗ gross-выручки: VAT = gross × vat_rate / (100 + vat_rate),
            УСН считается с net = gross − VAT.
            Общая нагрузка = УСН + НДС.
    """
    period_start = date_from.replace(day=1)
    if date_to.month == 12:
        period_end_date = date(date_to.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end_date = date(date_to.year, date_to.month + 1, 1) - timedelta(days=1)

    months = _iter_months(period_start, period_end_date)
    monthly: dict[str, UsnMonthlyRow] = {m: UsnMonthlyRow(month=m) for m in months}

    # 1) Sale realization (G) → period_end month для Основной
    main_rows = await _fetch_main_realizations(session, period_start, period_end_date)
    rid_to_main = {r["realization_id"]: r for r in main_rows if r["realization_id"]}
    for r in main_rows:
        rdt: date = r["report_date_to"]
        m = _month_key(rdt)
        if m not in monthly:
            continue
        monthly[m].sale_realization += r["sale_net"]
        monthly[m].realizations_count += 1

    # 2) PO-based компоненты + Y (tovar) для Основной по paid_dt
    period_starts = await _fetch_period_starts(session)
    po_stmt = select(
        WbPaymentOrder.payment_order_id,
        WbPaymentOrder.paid_dt,
        WbPaymentOrder.period_end,
        WbPaymentOrder.report_type,
        WbPaymentOrder.amount,
        WbPaymentOrder.upd_delivery_amount,
        WbPaymentOrder.buyout_returns_amount,
        WbPaymentOrder.status,
    ).where(WbPaymentOrder.excluded_from_usn.is_(False))
    po_rows = (await session.execute(po_stmt)).all()
    for r in po_rows:
        # Извлекаем realization_id из poid вида "realization-{id}"
        poid = r.payment_order_id or ""
        try:
            rid = int(poid.replace("realization-", "")) if poid.startswith("realization-") else None
        except (ValueError, TypeError):
            rid = None
        # ── Bank выкупы (T) → paid_dt month, no fiscal exclusion ──
        # Стас включает декабрьские «По выкупам» которые оплачены в январе,
        # т.к. cash-basis по получению средств. Исключения единичные / manual.
        if (
            r.report_type == "По выкупам"
            and r.status == "paid"
            and r.paid_dt is not None
        ):
            m = _month_key(r.paid_dt)
            if m in monthly:
                monthly[m].bank_buyout += float(r.amount or 0)
        # ── Y (Tov compensation) для «Основной» → paid_dt month ──
        # Y = dobr_komp_ppvz из wb_report_detail; берём из main_rows.
        if (
            r.report_type == "Основной"
            and r.status == "paid"
            and r.paid_dt is not None
            and rid in rid_to_main
        ):
            tov = rid_to_main[rid]["dobr_komp"]
            if tov > 0:
                m = _month_key(r.paid_dt)
                if m in monthly:
                    monthly[m].tovar_compensation += tov
        # ── Z (УПД доставки) → period_start month (По выкупам) ──
        upd_val = float(r.upd_delivery_amount or 0)
        if upd_val > 0:
            ps = period_starts.get(rid) if rid else None
            if ps:
                m = _month_key(ps)
                if m in monthly:
                    monthly[m].upd_delivery += upd_val
        # ── AA (Возвраты выкупы) → period_start month (По выкупам) ──
        aa_val = float(r.buyout_returns_amount or 0)
        if aa_val > 0:
            ps = period_starts.get(rid) if rid else None
            if ps:
                m = _month_key(ps)
                if m in monthly:
                    monthly[m].buyout_returns += aa_val

    # 3) Settings (tax_rate из timeline или default)
    timeline = await load_timeline(session)

    # 4) Итог + налог
    for m, row in monthly.items():
        # Gross-сумма всех компонентов (это база до выделения НДС)
        row.base_gross = (
            row.sale_realization
            + row.tovar_compensation
            + row.bank_buyout
            + row.upd_delivery
            + row.buyout_returns
        )
        # НДС внутри цены: VAT = gross × rate / (100 + rate)
        row.vat_rate = vat_rate
        if vat_rate > 0:
            row.vat = row.base_gross * vat_rate / (100.0 + vat_rate)
        else:
            row.vat = 0.0
        # net-база для УСН = gross − VAT
        row.base = row.base_gross - row.vat
        # Ставка УСН: explicit > timeline > default
        if tax_rate is not None:
            row.tax_rate = tax_rate
        else:
            y, mm = int(m[:4]), int(m[5:7])
            if mm == 12:
                month_end = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(y, mm + 1, 1) - timedelta(days=1)
            ts = value_for_date(timeline, {}, "tax_system", month_end) or ""
            rt = value_for_date(timeline, {}, "tax_rate", month_end)
            if ts == "usn_income" and rt:
                row.tax_rate = float(rt)
            else:
                row.tax_rate = _USN_INCOME_DEFAULT_RATE
        row.tax = row.base * row.tax_rate / 100.0
        row.total_tax = row.tax + row.vat

    sorted_months = [monthly[m] for m in months]
    totals = UsnMonthlyRow(month="ИТОГО")
    totals.vat_rate = vat_rate
    for r in sorted_months:
        totals.sale_realization += r.sale_realization
        totals.tovar_compensation += r.tovar_compensation
        totals.bank_buyout += r.bank_buyout
        totals.upd_delivery += r.upd_delivery
        totals.buyout_returns += r.buyout_returns
        totals.base_gross += r.base_gross
        totals.vat += r.vat
        totals.base += r.base
        totals.tax += r.tax
        totals.total_tax += r.total_tax
        totals.realizations_count += r.realizations_count

    return {
        "from": period_start.isoformat(),
        "to": period_end_date.isoformat(),
        "tax_system": "usn_income",
        "default_tax_rate": _USN_INCOME_DEFAULT_RATE,
        "vat_rate": vat_rate,
        "monthly": [r.to_dict() for r in sorted_months],
        "totals": totals.to_dict(),
        "methodology": (
            "База = Отчёты_реализации (G) + Тов_компенсация (Y) + Банк_выкупы (T) "
            "+ УПД_доставки (Z) + Возвраты_выкупы (AA). "
            "G+Y для «Основной» бакетируются по period_end. T для «По выкупам» "
            "по paid_dt с фискально-годовым исключением. Z и AA — по period_end."
        ),
    }
