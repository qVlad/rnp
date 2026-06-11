"""Налоговый отчёт АУСН «Доходы» (8 %) — методика бухгалтера Стаса.

Воспроизводит расчёт из xlsx «Стас Разметка банка с 01.01.2026.xlsx» 1:1.
В отличие от services/tax_report.py (который покрывает УСН/АУСН «Доходы −
Расходы» с COGS и НДС), здесь — простая месячная свёртка для режима
«Доходы»: tax = база × ставка, без вычетов.

Методика (лист «Итоги» в xlsx):

    База_месяца = Банк_месяца + ВЗЗ_отчёты_месяца + УПД_доставки_месяца
    Налог       = База × ставка   (АУСН «Доходы» = 8 %)

Где:
    Банк          — sum(ppvz_for_pay net) по отчётам, дата зачисления которых
                    попадает в месяц. Реальной даты зачисления в БД нет
                    (Стас вносит вручную из выписки), используем proxy:
                    pay_date = report_date_to + offset_days (по умолчанию 14).

    ВЗЗ_отчёты    — sum(retail_amount_net − ppvz_for_pay_net) по отчётам
                    "Основной", у которых report_date_to в месяце. Это
                    удержания WB (комиссия / логистика / хранение …),
                    оформленные взаимозачётом услуг — для АУСН «Доходы»
                    они тоже признаются доходом, потому что WB провёл
                    встречную услугу.

    УПД_доставки  — sum(WbRedeemNotification.total_sum_with_vat) по дате
                    уведомления (notification_date) в месяце.

    Возвраты_Выкупы (информационно, в базу НЕ входит) — sum(ppvz_for_pay)
                    для supplier_oper_name='Возврат'.

Сумма Банк + ВЗЗ ≈ Gross Sale (gross retail_amount), что соответствует
букве УСН/АУСН «Доходы»: налог берётся со всей выручки. Разделение нужно
только чтобы под каждое слагаемое был свой первичный документ для ФНС.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbPaymentOrder, WbRedeemNotification, WbReportDetail
from app.services.period_aggregates import OP_RETURN, OP_SALE
from app.services.pnl_builder import DEFAULT_TAX_RATE
from app.services.settings_timeline import load_timeline, value_for_date

# Если в settings не задано — АУСН «Доходы» = 8 %.
_AUSN_INCOME_DEFAULT_RATE = 8.0


@dataclass
class AusnMonthlyRow:
    """Одна строка месячной свёртки."""
    month: str  # 'YYYY-MM'
    bank: float = 0.0  # net ppvz_for_pay по дате оплаты в месяце
    vzz_reports: float = 0.0  # удержания WB по «Основным» отчётам месяца
    upd_delivery: float = 0.0  # WbRedeemNotification по notification_date в месяце
    base: float = 0.0  # = bank + vzz_reports + upd_delivery
    tax_system: str = "ausn_income"
    tax_rate: float = _AUSN_INCOME_DEFAULT_RATE
    tax: float = 0.0
    # Информационно (не входит в базу):
    buyback_returns: float = 0.0  # net ppvz по «Возврат» в месяце
    realizations_count: int = 0  # сколько отчётов попало в bank-агрегат

    def to_dict(self) -> dict[str, Any]:
        return {
            k: (round(v, 2) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
        }


@dataclass
class AusnReportRow:
    """Одна строка по отдельному WB-отчёту реализации (для drill-down)."""
    realization_id: int
    report_date_from: date
    report_date_to: date
    pay_date_proxy: date
    report_type: str  # 'Основной' / 'По выкупам' (по supplier_oper_name)
    sale_gross: float = 0.0       # sum(retail_amount net = Продажа − Возврат)
    bank_amount: float = 0.0       # net ppvz_for_pay = Итого к оплате
    vzz_amount: float = 0.0        # sale_gross − bank_amount = удержания WB
    month: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            k: (
                round(v, 2)
                if isinstance(v, float)
                else (v.isoformat() if isinstance(v, date) else v)
            )
            for k, v in self.__dict__.items()
        }


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _iter_months(date_from: date, date_to: date) -> list[str]:
    """Список 'YYYY-MM' от date_from до date_to (включительно)."""
    out: list[str] = []
    y, m = date_from.year, date_from.month
    end_y, end_m = date_to.year, date_to.month
    while (y, m) <= (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


async def _fetch_realization_aggregates(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """Группируем wb_report_detail по realization_id, считаем все поля
    нужные для методики Стаса (формулы выведены reverse-engineering xlsx
    «Стас Разметка банка»):

        G (Продажа)         = retail_amount_net = SUM(retail_amount Продажа − Возврат)
        Y (Тов. компенсация) = SUM(ppvz_for_pay) для supplier_oper_name
                              ='Добровольная компенсация при возврате'
        T (Итого к оплате)   = ppvz_for_pay_net + Y
                              − SUM(delivery_rub) − SUM(storage_fee)
                              − SUM(deduction) − SUM(penalty)
        ВЗЗ (X)             = G − T + Y   ⇔   доход признанный через
                              взаимозачёт услуг WB (комиссия + логистика +
                              хранение + удержания + штрафы). Для отчётов
                              «По выкупам» ВЗЗ обнуляется (методика Стаса).

    «По выкупам» определяется через наличие соответствующей записи в
    wb_redeem_notification (notification_number = realization_id).

    Расширенный диапазон по report_date_to (±60 дней / +30 дней) — чтобы
    захватить отчёты с paid_dt в нужном месяце даже если период раньше.
    """
    is_dobr = WbReportDetail.supplier_oper_name == "Добровольная компенсация при возврате"
    sale_amt_net = (
        func.sum(case((OP_SALE, WbReportDetail.retail_amount), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.retail_amount), else_=0))
    ).label("sale_net")
    ppvz_net = (
        func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.ppvz_for_pay), else_=0))
    ).label("ppvz_net")
    dobr_komp = func.sum(
        case((is_dobr, WbReportDetail.ppvz_for_pay), else_=0)
    ).label("dobr_komp")
    # Прочие ppvz_for_pay строки (не Продажа, не Возврат, не Добровольная
    # компенсация): «Корректировка эквайринга», «Компенсация скидки по
    # программе лояльности» и пр. Эти движения тоже идут в Итого к оплате
    # с их знаком (обычно мелкие корректировки ±). Учитываем для совпадения
    # с расчётом бухгалтера до копейки.
    other_ppvz = func.sum(
        case(
            (
                ~OP_SALE & ~OP_RETURN & ~is_dobr,
                WbReportDetail.ppvz_for_pay,
            ),
            else_=0,
        )
    ).label("other_ppvz")
    delivery = func.sum(WbReportDetail.delivery_rub).label("delivery")
    storage = func.sum(WbReportDetail.storage_fee).label("storage")
    deduction = func.sum(WbReportDetail.deduction).label("deduction")
    penalty = func.sum(WbReportDetail.penalty).label("penalty")
    returns_ppvz = func.sum(
        case((OP_RETURN, WbReportDetail.ppvz_for_pay), else_=0)
    ).label("returns_ppvz")

    stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
            sale_amt_net,
            ppvz_net,
            dobr_komp,
            other_ppvz,
            delivery,
            storage,
            deduction,
            penalty,
            returns_ppvz,
        )
        .where(WbReportDetail.report_date_to.is_not(None))
        .where(WbReportDetail.report_date_to >= date_from - timedelta(days=60))
        .where(WbReportDetail.report_date_to <= date_to + timedelta(days=30))
        .group_by(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
        )
        .order_by(WbReportDetail.report_date_to)
    )
    rows = (await session.execute(stmt)).all()

    # Загружаем realization_ids, которые числятся в wb_redeem_notification
    # — это «По выкупам» отчёты.
    from app.db.models import WbRedeemNotification  # noqa: WPS433
    redeem_ids_stmt = select(WbRedeemNotification.notification_number)
    redeem_ids = {
        int(rid) for (rid,) in (await session.execute(redeem_ids_stmt)).all()
        if rid and str(rid).isdigit()
    }

    out: list[dict[str, Any]] = []
    for r in rows:
        rid = int(r.realization_id) if r.realization_id else None
        report_type = "По выкупам" if rid in redeem_ids else "Основной"
        sale_net = float(r.sale_net or 0)
        ppvz = float(r.ppvz_net or 0)
        dk = float(r.dobr_komp or 0)
        other = float(r.other_ppvz or 0)
        dlv = float(r.delivery or 0)
        stg = float(r.storage or 0)
        ded = float(r.deduction or 0)
        pen = float(r.penalty or 0)
        # T = Итого к оплате = sum(все ppvz_for_pay со знаками) − удержания.
        # Включает Корректировка эквайринга и пр. (other_ppvz).
        itogo = ppvz + dk + other - dlv - stg - ded - pen
        # ВЗЗ = G − T + Y (для Основной) / 0 (для По выкупам, методика Стаса)
        vzz = sale_net - itogo + dk if report_type == "Основной" else 0.0
        out.append({
            "realization_id": rid,
            "report_date_from": r.report_date_from,
            "report_date_to": r.report_date_to,
            "sale_net": sale_net,
            "ppvz_net": ppvz,
            "itogo_to_pay": itogo,
            "vzz": vzz,
            "returns_ppvz": float(r.returns_ppvz or 0),
            "report_type": report_type,
        })
    return out


async def build_ausn_monthly_report(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    pay_offset_days: int = 10,
    pay_date_source: str = "auto",
) -> dict[str, Any]:
    """Месячная свёртка АУСН «Доходы».

    Параметры:
        date_from / date_to — диапазон месяцев. Включаются полностью все
            месяцы, в которые попадают эти даты.
        pay_offset_days — сколько дней прибавлять к report_date_to чтобы
            получить proxy для даты зачисления денег WB → р/с (используется
            если pay_date_source != 'actual'). Default 10.
        pay_date_source — источник даты зачисления:
            - 'auto' (default): если в wb_payment_order есть paid строки
              за нужный период → берём `paid_dt` оттуда; иначе proxy.
            - 'actual': только wb_payment_order.paid_dt (Bank-агрегат
              строится напрямую из импортированной «Истории платежей»);
              если данных нет — Банк = 0 за этот месяц.
            - 'proxy': только report_date_to + pay_offset_days, payment
              orders игнорируются.
    """
    # Раздвигаем диапазон до полных месяцев
    period_start = date_from.replace(day=1)
    if date_to.month == 12:
        period_end = date(date_to.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(date_to.year, date_to.month + 1, 1) - timedelta(days=1)

    # 1) Аггрегаты отчётов реализации
    realizations = await _fetch_realization_aggregates(
        session, period_start, period_end
    )

    # 1.5) Payment orders — Bank-агрегат по paid_dt (только paid строки).
    po_stmt = (
        select(
            WbPaymentOrder.payment_order_id,
            WbPaymentOrder.paid_dt,
            WbPaymentOrder.amount,
            WbPaymentOrder.status,
            WbPaymentOrder.period_end,
            WbPaymentOrder.report_type,
            WbPaymentOrder.upd_delivery_amount,
        )
        .where(WbPaymentOrder.paid_dt.is_not(None))
        .where(WbPaymentOrder.paid_dt >= period_start)
        .where(WbPaymentOrder.paid_dt <= period_end)
        .where(WbPaymentOrder.status == "paid")
        # Bookkeeper override — не учитываем помеченные отчёты в Bank.
        .where(WbPaymentOrder.excluded_from_ausn.is_(False))
    )
    po_rows = (await session.execute(po_stmt)).all()

    # 1.6) УПД доставки бакетируется по period_end (а не paid_dt) — методика
    # Стаса: услуги признаются когда оказаны. Отдельный запрос — независимый
    # от paid_dt, чтобы захватить ещё неоплаченные отчёты с УПД.
    upd_stmt = (
        select(
            WbPaymentOrder.period_end,
            func.sum(WbPaymentOrder.upd_delivery_amount).label("upd"),
        )
        .where(WbPaymentOrder.upd_delivery_amount > 0)
        .where(WbPaymentOrder.period_end.is_not(None))
        .where(WbPaymentOrder.period_end >= period_start)
        .where(WbPaymentOrder.period_end <= period_end)
        .where(WbPaymentOrder.excluded_from_ausn.is_(False))
        .group_by(WbPaymentOrder.period_end)
    )
    upd_rows = (await session.execute(upd_stmt)).all()
    has_payment_orders = len(po_rows) > 0
    # Решаем фактический источник
    if pay_date_source == "auto":
        effective_source = "actual" if has_payment_orders else "proxy"
    else:
        effective_source = pay_date_source

    # 2) Уведомления о выкупе (УПД доставки)
    redeem_stmt = (
        select(
            WbRedeemNotification.notification_date,
            func.sum(WbRedeemNotification.total_sum_with_vat).label("amount"),
        )
        .where(WbRedeemNotification.notification_date >= period_start)
        .where(WbRedeemNotification.notification_date <= period_end)
        .group_by(WbRedeemNotification.notification_date)
    )
    redeem_rows = (await session.execute(redeem_stmt)).all()

    # 3) Settings timeline (ставка)
    timeline = await load_timeline(session)

    # 4) Месячная свёртка
    months = _iter_months(period_start, period_end)
    monthly: dict[str, AusnMonthlyRow] = {m: AusnMonthlyRow(month=m) for m in months}
    realization_rows: list[AusnReportRow] = []

    for r in realizations:
        rdt: date = r["report_date_to"]
        pay_date_proxy = rdt + timedelta(days=pay_offset_days)
        bank_month_proxy = _month_key(pay_date_proxy)
        vzz_month = _month_key(rdt)
        itogo = r["itogo_to_pay"]
        vzz = r["vzz"]  # уже = 0 для «По выкупам» из _fetch_realization_aggregates

        # Bank — только если effective_source='proxy' (если 'actual' —
        # bank-агрегат строим ниже из payment_orders).
        if effective_source == "proxy" and bank_month_proxy in monthly:
            monthly[bank_month_proxy].bank += itogo
            monthly[bank_month_proxy].realizations_count += 1
            monthly[bank_month_proxy].buyback_returns += r["returns_ppvz"]

        # ВЗЗ — по period_end_to месяца. vzz уже обнулён для «По выкупам».
        if vzz_month in monthly:
            monthly[vzz_month].vzz_reports += vzz

        realization_rows.append(AusnReportRow(
            realization_id=r["realization_id"],
            report_date_from=r["report_date_from"],
            report_date_to=rdt,
            pay_date_proxy=pay_date_proxy,
            report_type=r["report_type"],
            sale_gross=r["sale_net"],
            bank_amount=itogo,
            vzz_amount=vzz,
            month=bank_month_proxy,
        ))

    # Bank-агрегат из payment_orders.paid (если 'actual').
    # Бакетируется по paid_dt — это правило по умолчанию. Единственное
    # исключение (методика Стаса для фискально-годового перехода): отчёт
    # типа «Основной» с period_end в предыдущем календарном году НЕ
    # включается в Bank нового года — он уже учтён в декларации за
    # прошлый год. Для «По выкупам» этого правила нет (мелкие выкупные
    # отчёты признаются cash-basis независимо от фискального года).
    if effective_source == "actual":
        for poid, paid_dt, amount, status, p_end, p_rtype, _upd in po_rows:
            target_month = _month_key(paid_dt)
            # Фискально-годовой переход: исключаем Основной отчёты,
            # период которых закрыт в прошлом году.
            if (
                p_end is not None
                and p_rtype == "Основной"
                and p_end.year < paid_dt.year
            ):
                continue
            if target_month in monthly:
                monthly[target_month].bank += float(amount or 0)
                monthly[target_month].realizations_count += 1

    # УПД доставки = sum(WbPaymentOrder.upd_delivery_amount) по period_end месяца
    # (Стас «УПД Доставка по выкупу» — только delivery-портация выкупа).
    # BUG (review 2026-06-10): РАНЬШЕ при пустых payment-orders за месяц был
    # fallback на WbRedeemNotification.total_sum_with_vat — но это ПОЛНАЯ сумма
    # выкупа (~×80 от delivery-УПД), он завышал налоговую базу (напр. май:
    # 49 312 / 371 676 вместо реальных 4 514.14). Fallback УДАЛЁН: если за
    # месяц нет payment-orders с upd_delivery_amount → УПД доставки = 0
    # (данные ещё не импортированы; честный 0 лучше завышенной базы).
    # `redeem_rows` оставлены для возможной отдельной справки, в базу не идут.
    for p_end, upd in upd_rows:
        m = _month_key(p_end)
        if m in monthly:
            monthly[m].upd_delivery += float(upd or 0)
    _ = redeem_rows  # намеренно не используется в базе (см. коммент выше)

    # 5) База + налог
    for m, row in monthly.items():
        row.base = row.bank + row.vzz_reports + row.upd_delivery
        # Берём ставку на конец месяца (если в timeline есть смена)
        y, mm = int(m[:4]), int(m[5:7])
        if mm == 12:
            month_end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(y, mm + 1, 1) - timedelta(days=1)
        # tax_system / tax_rate из timeline (empty static — статика не нужна)
        ts = (
            value_for_date(timeline, {}, "tax_system", month_end)
            or "ausn_income"
        )
        rate = float(
            value_for_date(timeline, {}, "tax_rate", month_end)
            or DEFAULT_TAX_RATE.get(ts, _AUSN_INCOME_DEFAULT_RATE)
        )
        row.tax_system = ts
        row.tax_rate = rate
        row.tax = row.base * rate / 100.0

    # 6) Totals
    sorted_months = [monthly[m] for m in months]
    totals = AusnMonthlyRow(month="ИТОГО")
    for r in sorted_months:
        totals.bank += r.bank
        totals.vzz_reports += r.vzz_reports
        totals.upd_delivery += r.upd_delivery
        totals.base += r.base
        totals.tax += r.tax
        totals.buyback_returns += r.buyback_returns
        totals.realizations_count += r.realizations_count

    bank_source_label = (
        f"actual (XLSX «История платежей», {len(po_rows)} заявок)"
        if effective_source == "actual"
        else f"proxy (report_date_to + {pay_offset_days} дн)"
    )
    return {
        "from": period_start.isoformat(),
        "to": period_end.isoformat(),
        "pay_offset_days": pay_offset_days,
        "pay_date_source_requested": pay_date_source,
        "pay_date_source_effective": effective_source,
        "payment_orders_paid_count": len(po_rows),
        "monthly": [r.to_dict() for r in sorted_months],
        "totals": totals.to_dict(),
        "realizations": [r.to_dict() for r in realization_rows],
        "methodology": (
            "База_месяца = Банк + ВЗЗ_отчёты + УПД_доставки. "
            f"Налог = База × ставка АУСН. Источник Банка: {bank_source_label}. "
            "ВЗЗ = retail_amount_net − ppvz_for_pay_net (удержания WB через "
            "взаимозачёт услуг). УПД доставки = wb_redeem_notification "
            "по notification_date. Возвраты Выкупы — справочно, в базу "
            "не входят."
        ),
    }
