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
    """Группируем wb_report_detail по realization_id и собираем поля
    отчёта: gross sale (retail_amount net), bank (ppvz_for_pay net),
    период отчёта.

    Берём расширенный диапазон по report_date_to: [date_from − 30d, date_to + 30d]
    чтобы захватить отчёты, чья pay_date_proxy = report_date_to + offset_days
    может оказаться в нужном месяце даже если сам период отчёта — нет.
    """
    sale_amt_net = (
        func.sum(case((OP_SALE, WbReportDetail.retail_amount), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.retail_amount), else_=0))
    ).label("sale_net")
    ppvz_net = (
        func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.ppvz_for_pay), else_=0))
    ).label("ppvz_net")
    returns_ppvz = func.sum(
        case((OP_RETURN, WbReportDetail.ppvz_for_pay), else_=0)
    ).label("returns_ppvz")
    has_sale = func.bool_or(OP_SALE).label("has_sale")
    has_return = func.bool_or(OP_RETURN).label("has_return")

    stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
            sale_amt_net,
            ppvz_net,
            returns_ppvz,
            has_sale,
            has_return,
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
    out: list[dict[str, Any]] = []
    for r in rows:
        # Эвристика типа отчёта: если в realization есть строки только для
        # «Возврат» (без «Продажа») — считаем «По выкупам». В реальности WB
        # не даёт явный type через finance API; в xlsx бухгалтер видит его
        # из «Тип отчета» в выгрузке Sheet1. Для tax-base разница лишь в
        # bank-агрегате (по выкупам ВЗЗ обычно = 0).
        report_type = "По выкупам" if (r.has_return and not r.has_sale) else "Основной"
        out.append({
            "realization_id": r.realization_id,
            "report_date_from": r.report_date_from,
            "report_date_to": r.report_date_to,
            "sale_net": float(r.sale_net or 0),
            "ppvz_net": float(r.ppvz_net or 0),
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

    # 1.5) Payment orders (история платежей из ЛК WB, импорт XLSX)
    po_stmt = (
        select(
            WbPaymentOrder.payment_order_id,
            WbPaymentOrder.paid_dt,
            WbPaymentOrder.amount,
            WbPaymentOrder.status,
        )
        .where(WbPaymentOrder.paid_dt.is_not(None))
        .where(WbPaymentOrder.paid_dt >= period_start)
        .where(WbPaymentOrder.paid_dt <= period_end)
        .where(WbPaymentOrder.status == "paid")
    )
    po_rows = (await session.execute(po_stmt)).all()
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
        sale_net = r["sale_net"]
        ppvz_net = r["ppvz_net"]
        vzz = max(0.0, sale_net - ppvz_net)  # удержания WB ≥ 0

        # Bank — только если effective_source='proxy' (если 'actual' —
        # bank-агрегат строим ниже из payment_orders).
        if effective_source == "proxy" and bank_month_proxy in monthly:
            monthly[bank_month_proxy].bank += ppvz_net
            monthly[bank_month_proxy].realizations_count += 1
            monthly[bank_month_proxy].buyback_returns += r["returns_ppvz"]

        # ВЗЗ — только для «Основной» (у «По выкупам» удержание = 0 в моделе Стаса)
        if vzz_month in monthly and r["report_type"] == "Основной":
            monthly[vzz_month].vzz_reports += vzz

        realization_rows.append(AusnReportRow(
            realization_id=r["realization_id"],
            report_date_from=r["report_date_from"],
            report_date_to=rdt,
            pay_date_proxy=pay_date_proxy,
            report_type=r["report_type"],
            sale_gross=sale_net,
            bank_amount=ppvz_net,
            vzz_amount=vzz if r["report_type"] == "Основной" else 0.0,
            month=bank_month_proxy,
        ))

    # Bank-агрегат из payment_orders (если effective_source='actual')
    if effective_source == "actual":
        for poid, paid_dt, amount, status in po_rows:
            m = _month_key(paid_dt)
            if m in monthly:
                monthly[m].bank += float(amount or 0)
                monthly[m].realizations_count += 1

    for nd, amount in redeem_rows:
        m = _month_key(nd)
        if m in monthly:
            monthly[m].upd_delivery += float(amount or 0)

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
