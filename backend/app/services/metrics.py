"""Compute dashboard KPIs.

The dashboard uses operational data (orders + sales + ad stats) for the current
window — these are available with ~30 minute lag. Historical P&L uses the
report-detail table (1-2 day lag); see `pnl_builder.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Literal

from app.db.models import (
    Cogs,
    ExternalAdCost,
    Product,
    WbAdStatsDaily,
    WbFunnelDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.periods import Period, PeriodKey, get_period

Mode = Literal["preliminary", "final", "hybrid"]
# TASK-LEAD-054 — ортогональный toggle. См. period_aggregates.ReportingMode.
ReportingMode = Literal["operational", "financial"]


def _rd_period_predicates(
    start: datetime, end: datetime, reporting_mode: ReportingMode
) -> tuple:
    """Predicates для `WbReportDetail` по периоду с учётом reporting_mode.

    operational (default) — по `sale_dt` (datetime), полуоткрытый интервал
                            [start, end), как было раньше.
    financial             — по `rr_dt` (Date), закрытый интервал
                            [start.date(), end.date()-1day]. Конвертация
                            `end` обратно в inclusive (end-1d) нужна потому
                            что `sale_dt < end` это exclusive datetime, а
                            `rr_dt <= ?` это inclusive Date.

    Если `end` пришёл как 00:00 следующего дня (что и делает sale_dt_filter
    при экспирации rd_end из period), то `end.date() - 1day` это последний
    включённый календарный день — корректно.
    """
    if reporting_mode == "financial":
        d_from = start.date()
        # end — exclusive datetime в operational семантике; в financial
        # переходим к inclusive date — последний полный день = end.date() - 1
        d_to = end.date() - timedelta(days=1)
        return (
            WbReportDetail.rr_dt >= d_from,
            WbReportDetail.rr_dt <= d_to,
        )
    return (
        WbReportDetail.sale_dt >= start,
        WbReportDetail.sale_dt < end,
    )
# Final-mode aggregations match the WB seller cabinet «Выкупы» / «Возвраты»
# columns 1:1. Two pieces matter:
#   1) Filter Продажа / Возврат on `supplier_oper_name` (not doc_type_name).
#      doc_type=Продажа also catches «Возмещение за выдачу...», «Программа
#      лояльности», «Добровольная компенсация», which WB cabinet shows in its
#      own buckets (Потери/подмены, Лояльность) — not in «Выкупы».
#   2) WB further subtracts the ppvz_for_pay of «Добровольная компенсация при
#      возврате» from «Выкупы» (it counts as a buyback fee). Mirror that.
# Канонические наборы операций — единый источник в period_aggregates.
# Локальные алиасы оставлены для обратной совместимости со старыми
# in_(_SALE_NAMES) выражениями ниже.
from app.services.period_aggregates import (  # noqa: E402
    COMPENSATION_RETURN_NAMES as _COMPENSATION_NAMES,
    RETURN_NAMES as _RETURN_NAMES,
    SALE_NAMES as _SALE_NAMES,
)

D0 = Decimal("0")


def _nm_id_subq(brands: set[str] | None, nm_ids: set[int] | None = None):
    """Sub-select of nm_ids to scope an aggregate.

    `nm_ids` (DEV-062 global filters) takes priority — it's the already-resolved
    set of allowed nm_id (brands×categories×groups×articles ∩ RBAC). When given,
    callers pass `brands=None` (RBAC уже учтён в resolve_nm_scope).

    Otherwise falls back to brand-whitelist (manager RBAC scope):
    `None` ⇒ caller applies no filter (unrestricted role).
    Empty set ⇒ caller produces zero rows by design (manager w/o assignments,
    or global filter that matched nothing).
    """
    if nm_ids is not None:
        return select(Product.nm_id).where(Product.nm_id.in_(nm_ids))
    if brands is None:
        return None
    return select(Product.nm_id).where(Product.brand.in_(list(brands)))


def _pct_change(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _f(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


@dataclass
class KPI:
    key: str
    label: str
    value: float
    prev_value: float | None
    change_pct: float | None
    unit: str = ""
    tooltip: str = ""  # human-readable formula explanation, shown on hover

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": round(self.value, 2),
            "prev_value": round(self.prev_value, 2) if self.prev_value is not None else None,
            "change_pct": self.change_pct,
            "unit": self.unit,
            "tooltip": self.tooltip,
        }


async def _funnel_covers_period(
    session: AsyncSession, period_from: date, period_to: date
) -> bool:
    """Funnel ПОЛНОСТЬЮ покрывает [from, to] (есть строка на каждый день)?

    Используется для решения: брать orders/revenue/buyouts из funnel
    (Analytics API, ВКЛЮЧАЕТ рассрочку — parity с Воронкой ЛК) или fallback
    на wb_orders/wb_sales (Statistics API, без рассрочки). TASK-LEAD-153.

    DEV-058: раньше проверяли «есть хоть одна строка» — но funnel синкается
    только ~14 дней назад (DAYS_BACK), поэтому для периода вроде 18-24.05,
    где есть лишь 22-24, funnel-сумма теряла 18-21 → заказы 314 вместо 871.
    Теперь требуем покрытие КАЖДОГО дня; частичное покрытие → fallback на
    полный wb_orders. Сессия уже tenant-scoped (auto-фильтр через mixin).
    """
    stmt = (
        select(func.count(func.distinct(func.date(WbFunnelDaily.dt))))
        .select_from(WbFunnelDaily)
        .where(WbFunnelDaily.dt >= period_from, WbFunnelDaily.dt <= period_to)
    )
    days_present = int((await session.execute(stmt)).scalar() or 0)
    days_expected = (period_to - period_from).days + 1
    return days_present >= days_expected


async def _orders_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
) -> dict[str, float]:
    """Preliminary KPI заказов.

    TASK-LEAD-153: если у тенанта есть `wb_funnel_daily` за период — берём
    `orders` (gross, ВКЛЮЧАЯ рассрочку и отменённые — как Воронка ЛК) и
    `revenue_gross` (Σ orderSum) оттуда. `cancellations` и `orders_active`
    остаются из wb_orders — funnel их не отдаёт. Семантика «orders»
    изменилась: теперь это gross-цифра Воронки (была active без отмен).
    `orders_active` сохраняет старую семантику для UI, где это важно.

    Fallback на wb_orders (без рассрочки): если funnel ещё не синканулся.
    """
    sub = _nm_id_subq(brands, nm_ids)
    period_from = start.date()
    period_to = (end - timedelta(microseconds=1)).date()

    # Cancellations + orders_active — всегда из wb_orders (funnel не отдаёт).
    cancel_stmt = select(
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0
        ).label("orders_active"),
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 1), else_=0)), 0
        ).label("cancellations"),
    ).where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
    if sub is not None:
        cancel_stmt = cancel_stmt.where(WbOrder.nm_id.in_(sub))
    cancel_row = (await session.execute(cancel_stmt)).one()

    if await _funnel_covers_period(session, period_from, period_to):
        f_stmt = select(
            func.coalesce(func.sum(WbFunnelDaily.orders_count), 0).label("orders"),
            func.coalesce(
                func.sum(WbFunnelDaily.orders_sum_rub), 0
            ).label("revenue_gross"),
        ).where(
            WbFunnelDaily.dt >= period_from,
            WbFunnelDaily.dt <= period_to,
        )
        if sub is not None:
            f_stmt = f_stmt.where(WbFunnelDaily.nm_id.in_(sub))
        f_row = (await session.execute(f_stmt)).one()
        return {
            "orders": _f(f_row.orders),
            "orders_active": _f(cancel_row.orders_active),
            "revenue_gross": _f(f_row.revenue_gross),
            "cancellations": _f(cancel_row.cancellations),
        }

    # Fallback: legacy wb_orders aggregate (без рассрочки).
    fb_stmt = select(
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0
        ).label("orders"),
        func.coalesce(
            func.sum(
                case(
                    (WbOrder.is_cancel, 0),
                    else_=WbOrder.total_price * (1 - WbOrder.discount_percent / 100),
                )
            ),
            0,
        ).label("revenue_gross"),
    ).where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
    if sub is not None:
        fb_stmt = fb_stmt.where(WbOrder.nm_id.in_(sub))
    fb_row = (await session.execute(fb_stmt)).one()
    return {
        "orders": _f(fb_row.orders),
        "orders_active": _f(cancel_row.orders_active),
        "revenue_gross": _f(fb_row.revenue_gross),
        "cancellations": _f(cancel_row.cancellations),
    }


async def _sales_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
) -> dict[str, float]:
    """Preliminary KPI выкупов.

    TASK-LEAD-153: `sales` (выкупы) теперь из `wb_funnel_daily.buyouts_count`
    (Analytics API, нетит выкуп с возвратом как Воронка). `returns`,
    `for_pay_net`, `for_pay_returns` — из wb_sales (funnel не отдаёт payout).
    Fallback на wb_sales если funnel пуст.
    """
    sub = _nm_id_subq(brands, nm_ids)
    period_from = start.date()
    period_to = (end - timedelta(microseconds=1)).date()

    # Returns + payout — всегда из wb_sales.
    sale_stmt = select(
        func.coalesce(
            func.sum(case((WbSale.is_return, 1), else_=0)), 0
        ).label("returns"),
        func.coalesce(
            func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)), 0
        ).label("for_pay_net"),
        func.coalesce(
            func.sum(case((WbSale.is_return, WbSale.for_pay), else_=0)), 0
        ).label("for_pay_returns"),
        func.coalesce(
            func.sum(case((WbSale.is_return, 0), else_=1)), 0
        ).label("sales_legacy"),
    ).where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
    if sub is not None:
        sale_stmt = sale_stmt.where(WbSale.nm_id.in_(sub))
    sale_row = (await session.execute(sale_stmt)).one()

    if await _funnel_covers_period(session, period_from, period_to):
        f_stmt = select(
            func.coalesce(func.sum(WbFunnelDaily.buyouts_count), 0).label("sales"),
        ).where(
            WbFunnelDaily.dt >= period_from,
            WbFunnelDaily.dt <= period_to,
        )
        if sub is not None:
            f_stmt = f_stmt.where(WbFunnelDaily.nm_id.in_(sub))
        f_sales = (await session.execute(f_stmt)).scalar() or 0
        sales_value = _f(f_sales)
    else:
        sales_value = _f(sale_row.sales_legacy)

    return {
        "sales": sales_value,
        "returns": _f(sale_row.returns),
        "for_pay_net": _f(sale_row.for_pay_net),
        "for_pay_returns": _f(sale_row.for_pay_returns),
    }


async def _final_orders_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    reporting_mode: ReportingMode = "operational",
) -> dict[str, float]:
    """Final-mode orders: from wb_report_detail.

    Period filtering — см. `_rd_period_predicates`:
      operational — by **sale_dt** (date of physical buyout/return). WB cabinet
                    дашборда показывает «Выкупы»/«Возвраты» по sale_dt — возврат
                    прошлой недели остаётся в bucket'е прошлой недели.
      financial   — by **rr_dt** (когда платёжка попала в фин-отчёт). Для
                    сверки с разделом «Финансы → Реализация» в WB-кабинете
                    и с банковской выпиской.

    `report_detail` doesn't model "cancelled order" — only Продажа / Возврат
    rows. So orders = sales count, cancellations = 0.
    """
    revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
    is_compensation = WbReportDetail.supplier_oper_name.in_(_COMPENSATION_NAMES)
    stmt = select(
        # qty: only Продажа rows (compensation qty already excluded by supplier_oper_name filter)
        func.coalesce(func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0).label("orders"),
        # revenue: Продажа.retail_with_disc minus compensation.ppvz_for_pay
        # (WB cabinet treats voluntary compensation as a fee against «Выкупы» $)
        func.coalesce(
            func.sum(case((is_sale, revenue_field), else_=0))
            - func.sum(case((is_compensation, WbReportDetail.ppvz_for_pay), else_=0)),
            0,
        ).label("revenue_gross"),
    ).where(*_rd_period_predicates(start, end, reporting_mode))
    sub = _nm_id_subq(brands, nm_ids)
    if sub is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    orders = _f(row.orders)

    # report_detail has no "cancelled order" concept. To compute a sensible
    # buyout % (which the WB cabinet shows as buyouts / orders_total), we
    # need the order denominator from wb_orders (cohort by order_dt). We
    # expose it through the standard `cancellations` field so the existing
    # _compute_window_kpis formula does the right thing without branching.
    cancel_stmt = select(
        func.coalesce(func.sum(case((WbOrder.is_cancel, 1), else_=0)), 0).label("cancellations"),
        func.coalesce(func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0).label("active"),
    ).where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
    if sub is not None:
        cancel_stmt = cancel_stmt.where(WbOrder.nm_id.in_(sub))
    crow = (await session.execute(cancel_stmt)).one()
    # Buyout denominator = orders_count + cancellations = total wb_orders.
    # We set cancellations so that orders_count + cancellations = total wb_orders.
    total_orders = _f(crow.cancellations) + _f(crow.active)
    return {
        "orders": orders,
        "orders_active": orders,
        "revenue_gross": _f(row.revenue_gross),
        # synthetic: buyout = sales / (orders + cancellations) = sales / total_wb_orders
        "cancellations": max(0.0, total_orders - orders),
    }


async def _final_sales_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    reporting_mode: ReportingMode = "operational",
) -> dict[str, float]:
    """Final-mode sales: count and net payout from wb_report_detail.

    Filtered on supplier_oper_name (not doc_type_name) — same logic as
    _final_orders_aggregate. Period filtering via `_rd_period_predicates`
    (sale_dt vs rr_dt — см. doc там).
    """
    is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
    is_return = WbReportDetail.supplier_oper_name.in_(_RETURN_NAMES)
    stmt = select(
        func.coalesce(func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0).label("sales"),
        func.coalesce(func.sum(case((is_return, WbReportDetail.quantity), else_=0)), 0).label("returns"),
        func.coalesce(
            func.sum(case((is_sale, WbReportDetail.ppvz_for_pay), else_=0))
            - func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)),
            0,
        ).label("for_pay_net"),
        func.coalesce(
            func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)), 0
        ).label("for_pay_returns"),
    ).where(*_rd_period_predicates(start, end, reporting_mode))
    sub = _nm_id_subq(brands, nm_ids)
    if sub is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    return {
        "sales": _f(row.sales),
        "returns": _f(row.returns),
        "for_pay_net": _f(row.for_pay_net),
        "for_pay_returns": _f(row.for_pay_returns),
    }


async def _final_finance_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    reporting_mode: ReportingMode = "operational",
) -> dict[str, float]:
    """WB-кабинет «Доходы и расходы» по карточкам — финансовые поля.

    Все из wb_report_detail.* по sale_dt в периоде. Для preliminary mode
    возвращается dict с нулями (этих полей нет в orders/sales API).

    Колонки соответствуют WB-кабинету:
      Логистика  — Σ delivery_rub
      Хранение   — Σ storage_fee
      Штрафы     — Σ penalty
      Удержания  — Σ deduction
      Эквайринг  — Σ acquiring_fee
      Доплаты    — Σ additional_payment
      Комиссия   — Σ (retail_price_withdisc_rub − ppvz_for_pay − acquiring_fee)
                   для Продаж минус для Возвратов
    «Итог по товарам» = ppvz_net − (логистика+хранение+штрафы+удержания+эквайринг)
                      + доплаты — деньги на счёт за период.
    """
    is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
    is_return = WbReportDetail.supplier_oper_name.in_(_RETURN_NAMES)
    revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    # Net commission = (retail − ppvz − acquiring) for sales − returns.
    # The cabinet rolls acquiring into «Комиссия WB и эквайринг», so we
    # report commission *plus* acquiring separately and let the UI label them.
    commission_expr = revenue_field - WbReportDetail.ppvz_for_pay - func.coalesce(WbReportDetail.acquiring_fee, 0)
    stmt = select(
        func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("logistics"),
        func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
        func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
        func.coalesce(func.sum(WbReportDetail.deduction), 0).label("deduction"),
        # Acquiring net = Σ(Продажа) − Σ(Возврат). Без учёта rows-aggregate
        # (Корректировка эквайринга, Удержание, ...) — те идут отдельными KPI.
        func.coalesce(
            func.sum(case((is_sale, WbReportDetail.acquiring_fee), else_=0))
            - func.sum(case((is_return, WbReportDetail.acquiring_fee), else_=0)),
            0,
        ).label("acquiring"),
        func.coalesce(func.sum(WbReportDetail.additional_payment), 0).label("additional"),
        func.coalesce(
            func.sum(case((is_sale, commission_expr), else_=0))
            - func.sum(case((is_return, commission_expr), else_=0)),
            0,
        ).label("commission"),
        # ppvz net (Продажа − Возврат) — already provided by _final_sales_aggregate
        # but we duplicate here to compute «Итог по товарам» self-contained.
        func.coalesce(
            func.sum(case((is_sale, WbReportDetail.ppvz_for_pay), else_=0))
            - func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)),
            0,
        ).label("ppvz_net"),
    ).where(*_rd_period_predicates(start, end, reporting_mode))
    sub = _nm_id_subq(brands, nm_ids)
    if sub is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    logistics = _f(row.logistics)
    # Хранение: предпочитаем paid_storage (точные суточные начисления per nm)
    # с fallback на storage_fee из report_detail. Это даёт совпадение между
    # Dashboard / P&L / Units (раньше каждый брал свой источник).
    from app.services.storage_resolver import resolve_period_storage  # noqa: WPS433

    storage, _storage_src = await resolve_period_storage(
        session, start=start, end=end, brands_subq=sub
    )
    penalty = _f(row.penalty)
    deduction = _f(row.deduction)
    acquiring = _f(row.acquiring)
    additional = _f(row.additional)
    commission = _f(row.commission)
    ppvz_net = _f(row.ppvz_net)
    # Деньги на счёт по итогам периода: то что WB перечислит после всех удержаний.
    payout = ppvz_net - logistics - storage - penalty - deduction + additional
    return {
        "commission": commission,
        "commission_plus_acquiring": commission + acquiring,
        "logistics": logistics,
        "storage": storage,
        "penalty": penalty,
        "deduction": deduction,
        "acquiring": acquiring,
        "additional": additional,
        "payout_to_account": payout,
    }


def _empty_finance() -> dict[str, float]:
    return {
        "commission": 0.0,
        "commission_plus_acquiring": 0.0,
        "logistics": 0.0,
        "storage": 0.0,
        "penalty": 0.0,
        "deduction": 0.0,
        "acquiring": 0.0,
        "additional": 0.0,
        "payout_to_account": 0.0,
    }


async def _final_sold_units_and_cogs(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    cogs_map: dict[int, float],
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    reporting_mode: ReportingMode = "operational",
) -> tuple[float, float]:
    """Net sold quantity and COGS from wb_report_detail (sales − returns).

    Filtered by supplier_oper_name to match the WB cabinet's «Выкупы» и
    «Возвраты» buckets; период — sale_dt в operational режиме / rr_dt в
    financial (см. `_rd_period_predicates`).
    """
    stmt = (
        select(
            WbReportDetail.nm_id,
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name.in_(_SALE_NAMES), WbReportDetail.quantity),
                    (WbReportDetail.supplier_oper_name.in_(_RETURN_NAMES), -WbReportDetail.quantity),
                    else_=0,
                )
            ).label("units"),
        )
        .where(*_rd_period_predicates(start, end, reporting_mode))
        .group_by(WbReportDetail.nm_id)
    )
    sub = _nm_id_subq(brands, nm_ids)
    if sub is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(sub))
    rows = (await session.execute(stmt)).all()
    units = sum(int(r.units or 0) for r in rows if r.nm_id is not None)
    cogs = sum(
        int(r.units or 0) * cogs_map.get(int(r.nm_id), 0.0)
        for r in rows
        if r.nm_id is not None
    )
    return float(units), float(cogs)


async def _ad_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
) -> dict[str, float]:
    # NB: period.end is exclusive (next day at 00:00). For Date columns we
    # want stat_date < end.date() — NOT end.date() + 1day, which used to
    # include an extra day past the user's selection.
    stmt = select(
        func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
        func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("ad_clicks"),
        func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("ad_views"),
        func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("ad_orders"),
    ).where(
        WbAdStatsDaily.stat_date >= start.date(),
        WbAdStatsDaily.stat_date < end.date(),
    )
    sub = _nm_id_subq(brands, nm_ids)
    if sub is not None:
        stmt = stmt.where(WbAdStatsDaily.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    wb_ad_cost = _f(row.ad_cost)

    # External (off-WB) ad costs — bloggers, infographics, banners.
    # Three attribution levels (см. миграцию 0032):
    #   1. nm_id NOT NULL                    → SKU-level
    #   2. nm_id IS NULL, brand IS NOT NULL  → brand-level
    #   3. nm_id IS NULL, brand IS NULL      → company-wide
    # Manager-scope видит #1 (по своим nm) и #2 (по своим брендам), но
    # НЕ видит #3 (общие расходы компании).
    ext_stmt = select(
        func.coalesce(func.sum(ExternalAdCost.amount), 0).label("ext_cost")
    ).where(
        ExternalAdCost.spend_date >= start.date(),
        ExternalAdCost.spend_date < end.date(),
    )
    if sub is not None:
        ext_stmt = ext_stmt.where(
            or_(
                ExternalAdCost.nm_id.in_(sub),
                and_(
                    ExternalAdCost.nm_id.is_(None),
                    ExternalAdCost.brand.in_(brands or []),
                ),
            )
        )
    ext_cost = _f((await session.execute(ext_stmt)).scalar_one())

    return {
        "ad_cost": wb_ad_cost + ext_cost,
        "ad_cost_wb": wb_ad_cost,
        "ad_cost_external": ext_cost,
        "ad_clicks": _f(row.ad_clicks),
        "ad_views": _f(row.ad_views),
        "ad_orders": _f(row.ad_orders),
    }


async def _stocks_aggregate(
    session: AsyncSession, brands: set[str] | None = None, nm_ids: set[int] | None = None
) -> dict[str, float]:
    """Latest snapshot — total units & total cost (using current COGS)."""
    latest_dt = select(func.max(WbStockSnapshot.snapshot_dt)).scalar_subquery()
    stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.sum(WbStockSnapshot.quantity_full).label("qty"),
        )
        .where(WbStockSnapshot.snapshot_dt == latest_dt)
        .group_by(WbStockSnapshot.nm_id)
    )
    nm_sub = _nm_id_subq(brands, nm_ids)
    if nm_sub is not None:
        stmt = stmt.where(WbStockSnapshot.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()

    total_units = float(sum(_f(r.qty) for r in rows))

    cogs_map = await _latest_cogs_map(session, brands=brands, nm_ids=nm_ids)
    total_value = float(
        sum(_f(r.qty) * cogs_map.get(int(r.nm_id), 0.0) for r in rows)
    )
    return {"stock_units": total_units, "stock_value_at_cogs": total_value}


async def _latest_cogs_map(
    session: AsyncSession, brands: set[str] | None = None, nm_ids: set[int] | None = None
) -> dict[int, float]:
    stmt = select(
        Cogs.nm_id,
        Cogs.cost_rub,
        Cogs.packaging_rub,
        Cogs.fulfillment_rub,
        Cogs.valid_from,
    ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
    nm_sub = _nm_id_subq(brands, nm_ids)
    if nm_sub is not None:
        stmt = stmt.where(Cogs.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    out: dict[int, float] = {}
    for r in rows:
        nm = int(r.nm_id)
        if nm in out:
            continue
        out[nm] = _f(r.cost_rub) + _f(r.packaging_rub) + _f(r.fulfillment_rub)
    return out


def _compute_window_kpis(orders: dict, sales: dict, ad: dict) -> dict[str, float]:
    revenue_gross = orders["revenue_gross"]
    revenue_net = sales["for_pay_net"]
    orders_count = orders["orders"]
    cancellations = orders["cancellations"]
    returns = sales["returns"]
    sales_count = sales["sales"]
    ad_cost = ad["ad_cost"]

    # buyout %: WB seller cabinet defines it as
    #   выкупленные / заказанные (включая отменённые покупателем) × 100.
    total_orders = orders_count + cancellations
    buyout = (sales_count - returns) / total_orders * 100 if total_orders > 0 else 0.0
    # ДРР (доля рекламных расходов) — два варианта смотрят на одно и то же:
    #   - от заказов: реклама/выручка-по-заказам (как смотрят маркетологи)
    #   - от выкупов: реклама/чистая-выручка (как смотрит финансист)
    drr_orders = ad_cost / revenue_gross * 100 if revenue_gross > 0 else 0.0
    drr_sales = ad_cost / revenue_net * 100 if revenue_net > 0 else 0.0
    return_rate = returns / sales_count * 100 if sales_count > 0 else 0.0

    return {
        "revenue_gross": revenue_gross,
        "revenue_net": revenue_net,
        "orders": orders_count,
        "sales": sales_count,
        "returns": returns,
        "ad_cost": ad_cost,
        "ad_cost_wb": ad.get("ad_cost_wb", ad_cost),
        "ad_cost_external": ad.get("ad_cost_external", 0.0),
        "buyout_pct": buyout,
        "drr_pct": drr_orders,        # legacy alias = drr from orders
        "drr_orders_pct": drr_orders,
        "drr_sales_pct": drr_sales,
        "return_rate_pct": return_rate,
    }


async def _hybrid_cutoff(session: AsyncSession) -> datetime | None:
    """Возвращает datetime (UTC, +1 день после max report_date_to) — границу
    «закрытой» WB-территории. Дни до неё — final, после неё — preliminary.

    Если в БД нет ни одного report_detail — None (всё считается preliminary).
    """
    from app.db.models import WbReportDetail as _RD

    row = await session.execute(select(func.max(_RD.report_date_to)))
    max_to = row.scalar()
    if max_to is None:
        return None
    # +1 день — переход от закрытой недели к свежим данным
    return datetime.combine(
        max_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )


def _merge_dicts(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    """Поэлементное сложение dict'ов с float-значениями. Ключи объединяются."""
    out: dict[str, float] = dict(a)
    for k, v in b.items():
        out[k] = _f(out.get(k, 0)) + _f(v)
    return out


async def _hybrid_orders_or_sales(
    aggregate_fn_final,
    aggregate_fn_preliminary,
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None,
    cutoff: datetime | None,
    nm_ids: set[int] | None = None,
    reporting_mode: ReportingMode = "operational",
) -> dict[str, float]:
    """Hybrid: для дат до cutoff — final, после — preliminary. Складываем.

    `reporting_mode` влияет только на final-часть (wb_report_detail). Для
    preliminary (wb_orders/wb_sales) у нас нет аналога rr_dt — preliminary
    fn не принимает reporting_mode.
    """
    if cutoff is None or cutoff <= start:
        # Все дни — preliminary (нет закрытых отчётов или они старше start)
        return await aggregate_fn_preliminary(session, start, end, brands, nm_ids=nm_ids)
    if cutoff >= end:
        # Все дни — final (cutoff покрывает весь период)
        return await aggregate_fn_final(session, start, end, brands, nm_ids=nm_ids, reporting_mode=reporting_mode)
    # Mixed: [start, cutoff) — final; [cutoff, end) — preliminary
    final_part = await aggregate_fn_final(session, start, cutoff, brands, nm_ids=nm_ids, reporting_mode=reporting_mode)
    prelim_part = await aggregate_fn_preliminary(session, cutoff, end, brands, nm_ids=nm_ids)
    return _merge_dicts(final_part, prelim_part)


async def _hybrid_sold_units_and_cogs(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    cogs_map: dict[int, float],
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    cutoff: datetime | None = None,
    reporting_mode: ReportingMode = "operational",
) -> tuple[int, float]:
    """Hybrid sold units + COGS — split по cutoff и суммируем."""
    if cutoff is None or cutoff <= start:
        return await _sold_units_and_cogs(session, start, end, cogs_map, brands=brands, nm_ids=nm_ids)
    if cutoff >= end:
        return await _final_sold_units_and_cogs(
            session, start, end, cogs_map, brands=brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
    f_units, f_cogs = await _final_sold_units_and_cogs(
        session, start, cutoff, cogs_map, brands=brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
    )
    p_units, p_cogs = await _sold_units_and_cogs(session, cutoff, end, cogs_map, brands=brands, nm_ids=nm_ids)
    return f_units + p_units, f_cogs + p_cogs


async def compute_dashboard(
    session: AsyncSession,
    period_or_key: "PeriodKey | Period",
    brands: set[str] | None = None,
    mode: Mode = "preliminary",
    reporting_mode: ReportingMode = "operational",
    nm_ids: set[int] | None = None,
    multi_store: bool = False,
    store_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Build dashboard KPIs.

    `mode='preliminary'` (default) — orders/sales come from wb_orders/wb_sales,
    fast-updating but with cancellation noise on the right edge of the period.

    `mode='final'` — read from wb_report_detail. Final WB numbers, matches the
    WB seller cabinet exactly. Updated weekly, ~14 day lag for the most recent
    week.

    `mode='hybrid'` (10X-методика) — комбинированный: для уже закрытых
    WB-недель (где есть report_detail) берём final-цифры, для свежих
    дней — preliminary. Граница `cutoff = max(report_date_to) + 1d`.
    Если cutoff покрывает весь период → ведёт себя как final;
    если данных report_detail нет вообще → как preliminary.

    `reporting_mode` (TASK-LEAD-054) — ортогональный toggle, влияет только
    на final/hybrid (wb_report_detail). preliminary (orders/sales) от него
    не зависит — у тех таблиц нет аналога rr_dt.
      `operational` (default) — группировка по `sale_dt` (день выкупа), наш
                                текущий канон, совпадает с дашбордом WB.
      `financial`             — группировка по `rr_dt` (день платёжки), для
                                бухгалтерской сверки с WB-«Финансы → Реализация».
    """
    period: Period = (
        period_or_key if isinstance(period_or_key, Period) else get_period(period_or_key)
    )

    cutoff: datetime | None = None
    if mode == "hybrid":
        cutoff = await _hybrid_cutoff(session)

    if mode == "final":
        orders_fn = _final_orders_aggregate
        sales_fn = _final_sales_aggregate
        sold_fn = _final_sold_units_and_cogs
    elif mode == "preliminary":
        orders_fn = _orders_aggregate
        sales_fn = _sales_aggregate
        sold_fn = _sold_units_and_cogs
    else:
        # hybrid — уйдём в helper-обёртку ниже
        orders_fn = None
        sales_fn = None
        sold_fn = None

    # `reporting_mode` важен только для final/hybrid (wb_report_detail).
    # Для preliminary fn'ов (wb_orders/wb_sales) сигнатура не принимает его.
    rm_kw_final = {"reporting_mode": reporting_mode}
    if mode == "hybrid":
        curr_orders = await _hybrid_orders_or_sales(
            _final_orders_aggregate, _orders_aggregate,
            session, period.start, period.end, brands, cutoff, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
        prev_orders = await _hybrid_orders_or_sales(
            _final_orders_aggregate, _orders_aggregate,
            session, period.prev_start, period.prev_end, brands, cutoff, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
        curr_sales = await _hybrid_orders_or_sales(
            _final_sales_aggregate, _sales_aggregate,
            session, period.start, period.end, brands, cutoff, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
        prev_sales = await _hybrid_orders_or_sales(
            _final_sales_aggregate, _sales_aggregate,
            session, period.prev_start, period.prev_end, brands, cutoff, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
    elif mode == "final":
        curr_orders = await orders_fn(session, period.start, period.end, brands, nm_ids=nm_ids, **rm_kw_final)
        prev_orders = await orders_fn(session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids, **rm_kw_final)
        curr_sales = await sales_fn(session, period.start, period.end, brands, nm_ids=nm_ids, **rm_kw_final)
        prev_sales = await sales_fn(session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids, **rm_kw_final)
    else:
        # preliminary — _orders_aggregate / _sales_aggregate, без reporting_mode
        curr_orders = await orders_fn(session, period.start, period.end, brands, nm_ids=nm_ids)
        prev_orders = await orders_fn(session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids)
        curr_sales = await sales_fn(session, period.start, period.end, brands, nm_ids=nm_ids)
        prev_sales = await sales_fn(session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids)
    curr_ad = await _ad_aggregate(session, period.start, period.end, brands, nm_ids=nm_ids)
    prev_ad = await _ad_aggregate(session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids)
    stocks = await _stocks_aggregate(session, brands, nm_ids=nm_ids)

    curr = _compute_window_kpis(curr_orders, curr_sales, curr_ad)
    prev = _compute_window_kpis(prev_orders, prev_sales, prev_ad)

    cogs_map = await _latest_cogs_map(session, brands=brands, nm_ids=nm_ids)
    if mode == "hybrid":
        sold_units, sold_cogs = await _hybrid_sold_units_and_cogs(
            session, period.start, period.end, cogs_map, brands=brands, nm_ids=nm_ids,
            cutoff=cutoff, reporting_mode=reporting_mode,
        )
        _, prev_sold_cogs = await _hybrid_sold_units_and_cogs(
            session, period.prev_start, period.prev_end, cogs_map, brands=brands, nm_ids=nm_ids,
            cutoff=cutoff, reporting_mode=reporting_mode,
        )
    elif mode == "final":
        sold_units, sold_cogs = await sold_fn(
            session, period.start, period.end, cogs_map, brands=brands, nm_ids=nm_ids,
            reporting_mode=reporting_mode,
        )
        _, prev_sold_cogs = await sold_fn(
            session, period.prev_start, period.prev_end, cogs_map, brands=brands, nm_ids=nm_ids,
            reporting_mode=reporting_mode,
        )
    else:
        sold_units, sold_cogs = await sold_fn(
            session, period.start, period.end, cogs_map, brands=brands, nm_ids=nm_ids,
        )
        _, prev_sold_cogs = await sold_fn(
            session, period.prev_start, period.prev_end, cogs_map, brands=brands, nm_ids=nm_ids,
        )
    # Финансовые поля из wb_report_detail доступны в final и hybrid (берём
    # final-часть для closed-периода, для свежей части просто отсутствуют).
    if mode in ("final", "hybrid"):
        if mode == "hybrid" and cutoff is not None and cutoff > period.start and cutoff < period.end:
            # finance — только за final-часть [start, cutoff)
            fin = await _final_finance_aggregate(
                session, period.start, cutoff, brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
            )
            prev_fin_end = min(cutoff, period.prev_end)
            if prev_fin_end > period.prev_start:
                prev_fin = await _final_finance_aggregate(
                    session, period.prev_start, prev_fin_end, brands, nm_ids=nm_ids,
                    reporting_mode=reporting_mode,
                )
            else:
                prev_fin = _empty_finance()
        else:
            fin = await _final_finance_aggregate(
                session, period.start, period.end, brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
            )
            prev_fin = await _final_finance_aggregate(
                session, period.prev_start, period.prev_end, brands, nm_ids=nm_ids,
                reporting_mode=reporting_mode,
            )
    else:
        fin = _empty_finance()
        prev_fin = _empty_finance()

    # Чистая прибыль (full P&L profit) — нужен build_pnl. Он использует
    # wb_report_detail независимо от режима дашборда, так что результат
    # одинаков для preliminary/final. Lazy import чтобы не было кругового
    # импорта (pnl_builder сам импортирует metrics в reconciliation).
    from app.services.pnl_builder import build_pnl, build_pnl_consolidated  # noqa: WPS433

    pnl_from = period.start.date()
    pnl_to = (period.end - timedelta(days=1)).date()
    pnl_prev_from = period.prev_start.date()
    pnl_prev_to = (period.prev_end - timedelta(days=1)).date()
    if store_ids:
        # DEV-092: свод — полный P&L (per-tenant налоги/OPEX, pitfall #16),
        # а не contribution-margin по tenant_id IN.
        pnl_curr = await build_pnl_consolidated(
            session, store_ids=store_ids, date_from=pnl_from, date_to=pnl_to,
            granularity="month", brands=brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
        pnl_prev = await build_pnl_consolidated(
            session, store_ids=store_ids, date_from=pnl_prev_from, date_to=pnl_prev_to,
            granularity="month", brands=brands, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
    else:
        pnl_curr = await build_pnl(
            session, date_from=pnl_from, date_to=pnl_to, granularity="month",
            brands=brands, nm_ids=nm_ids, multi_store=multi_store, reporting_mode=reporting_mode,
        )
        pnl_prev = await build_pnl(
            session, date_from=pnl_prev_from, date_to=pnl_prev_to, granularity="month",
            brands=brands, nm_ids=nm_ids, multi_store=multi_store, reporting_mode=reporting_mode,
        )
    net_profit = _f(pnl_curr.get("totals", {}).get("profit", 0))
    prev_net_profit = _f(pnl_prev.get("totals", {}).get("profit", 0))

    # Contribution-margin (без OPEX / fixed_costs / налогов) — TASK-LEAD-034.
    # `profit_from_sales` в pnl_builder = revenue_after_vat − COGS − коммерческие
    # расходы (commission + delivery + storage + penalty + deduction + acquiring
    # + ad_cost + external_ad_cost + contractor_fees). Точно то, что просит
    # таска: «revenue_net − COGS − wb_удержания − реклама», без OPEX/налогов.
    pnl_totals = pnl_curr.get("totals", {})
    pnl_prev_totals = pnl_prev.get("totals", {})
    contribution_margin = _f(pnl_totals.get("profit_from_sales", 0))
    prev_contribution_margin = _f(pnl_prev_totals.get("profit_from_sales", 0))
    rev_after_vat = _f(pnl_totals.get("revenue_after_vat", 0))
    prev_rev_after_vat = _f(pnl_prev_totals.get("revenue_after_vat", 0))
    contribution_margin_pct = (
        (contribution_margin / rev_after_vat * 100) if rev_after_vat > 0 else 0.0
    )
    prev_contribution_margin_pct = (
        (prev_contribution_margin / prev_rev_after_vat * 100)
        if prev_rev_after_vat > 0
        else 0.0
    )

    margin_value = curr["revenue_net"] - sold_cogs - curr["ad_cost"]
    margin_pct = (margin_value / curr["revenue_net"] * 100) if curr["revenue_net"] > 0 else 0.0
    prev_margin_value = prev["revenue_net"] - prev_sold_cogs - prev["ad_cost"]
    prev_margin_pct = (
        (prev_margin_value / prev["revenue_net"] * 100) if prev["revenue_net"] > 0 else 0.0
    )
    # ROI / Рентабельность по COGS — сколько прибыли с каждого вложенного рубля себестоимости
    roi = (margin_value / sold_cogs * 100) if sold_cogs > 0 else 0.0
    prev_roi = (prev_margin_value / prev_sold_cogs * 100) if prev_sold_cogs > 0 else 0.0

    if mode == "hybrid":
        cutoff_str = cutoff.date().isoformat() if cutoff else "(нет данных)"
        src_orders = (
            f"hybrid: до {cutoff_str} — wb_report_detail; после — wb_orders"
        )
        src_revenue = (
            f"hybrid: до {cutoff_str} — Σ retail_price_withdisc_rub (Продажи − добровольные компенсации); "
            "после — Σ wb_orders.total_price × (1−discount)"
        )
        src_returns = (
            f"hybrid: до {cutoff_str} — wb_report_detail.Возврат; после — wb_sales.is_return"
        )
    else:
        src_orders = "wb_orders по order_dt" if mode == "preliminary" else "wb_report_detail.Продажа по sale_dt"
        src_revenue = "Σ retail_with_disc активных wb_orders" if mode == "preliminary" else (
            "Σ retail_price_withdisc_rub Продаж − ppvz_for_pay добровольных компенсаций"
        )
        src_returns = "wb_sales.is_return по sale_dt" if mode == "preliminary" else "wb_report_detail.Возврат по sale_dt"

    kpis = [
        KPI("revenue_gross", "Выручка (gross)", curr["revenue_gross"], prev["revenue_gross"],
            _pct_change(curr["revenue_gross"], prev["revenue_gross"]), "₽",
            f"Сумма заказанных товаров за период.\nИсточник ({mode}): {src_revenue}.\n"
            "Это «брутто» выручка — до WB-комиссии, логистики и налогов."),
        KPI("revenue_net", "Поступления от WB", curr["revenue_net"], prev["revenue_net"],
            _pct_change(curr["revenue_net"], prev["revenue_net"]), "₽",
            "Сумма после удержания WB-комиссии и эквайринга — то с чего ещё вычтут "
            "логистику/хранение/штрафы.\n"
            f"Формула: Σ ppvz_for_pay (Продажи − Возвраты).\nИсточник: {src_orders}.\n"
            "⚠ На странице P&L «Чистая выручка» имеет другое определение — это "
            "revenue_gross − returns (т.е. ДО комиссии WB)."),
        KPI("orders", "Заказы", curr["orders"], prev["orders"],
            _pct_change(curr["orders"], prev["orders"]), "шт",
            (
                "В режиме PRELIMINARY: активные заказы из wb_orders (без отменённых).\n"
                "В режиме FINAL: количество выкупленных единиц из wb_report_detail "
                "(supplier_oper_name='Продажа').\nЭто **разные** метрики; для total_orders "
                "(включая cancellations) смотрите страницу Юнит-экономика."
                f"\nИсточник ({mode}): {src_orders}."
            )),
        KPI("buyout_pct", "Выкуп", curr["buyout_pct"], prev["buyout_pct"],
            _pct_change(curr["buyout_pct"], prev["buyout_pct"]), "%",
            "% заказов которые покупатели выкупили из всех заказов (включая отменённые).\n"
            "Формула: (sales − returns) / (orders + cancellations) × 100.\n"
            "Совпадает с «% выкупа» в WB-кабинете."),
        KPI("returns", "Возвраты", curr["returns"], prev["returns"],
            _pct_change(curr["returns"], prev["returns"]), "шт",
            f"Кол-во возвратов за период.\nИсточник: {src_returns}."),
        KPI("ad_cost", "Реклама", curr["ad_cost"], prev["ad_cost"],
            _pct_change(curr["ad_cost"], prev["ad_cost"]), "₽",
            "Реклама = WB-кампании (advert API) + внешний маркетинг (блогеры, баннеры).\n"
            f"WB: {curr['ad_cost_wb']:,.0f} ₽   Внеш.: {curr['ad_cost_external']:,.0f} ₽.\n"
            "WB-кабинет «Реклама» в фин-отчёте может быть на 20-40 % больше — туда WB включает "
            "Boost / промо-инструменты которых нет в /adv/v3/fullstats. Это known issue WB API."),
        KPI("drr_pct", "ДРР (от заказов)", curr["drr_orders_pct"], prev["drr_orders_pct"],
            _pct_change(curr["drr_orders_pct"], prev["drr_orders_pct"]), "%",
            "Доля рекламных расходов от gross-выручки заказов.\n"
            "Формула: ad_cost / revenue_gross × 100.\n"
            "Используется маркетологами — показывает «съедает ли реклама заказы»."),
        KPI("drr_sales_pct", "ДРР (от выкупов)", curr["drr_sales_pct"], prev["drr_sales_pct"],
            _pct_change(curr["drr_sales_pct"], prev["drr_sales_pct"]), "%",
            "Доля рекламных расходов от чистой выручки (после WB-комиссии).\n"
            "Формула: ad_cost / revenue_net × 100.\n"
            "Используется финансистом — показывает «сколько % реальных денег уходит на рекламу»."),
        KPI("margin", "Маржинальная прибыль", margin_value, prev_margin_value,
            _pct_change(margin_value, prev_margin_value), "₽",
            "Маржинальная прибыль = чистая выручка − COGS (закупка+упаковка+фулфилмент) − реклама.\n"
            "Формула: revenue_net − sold_cogs − ad_cost.\n"
            "Это contribution-margin: НЕ включает OPEX (зарплаты/аренда), налоги, НДС, fixed-costs.\n"
            "Полная прибыль компании — на странице P&L."),
        KPI("margin_pct", "Маржа", margin_pct, prev_margin_pct,
            _pct_change(margin_pct, prev_margin_pct), "%",
            "Маржа в % от чистой выручки.\nФормула: маржинальная прибыль / revenue_net × 100.\n"
            "Норма для маркетплейса: 5-25 %."),
        KPI("roi_pct", "Рентабельность (ROI)", roi, prev_roi,
            _pct_change(roi, prev_roi), "%",
            "Рентабельность инвестиций в товар.\nФормула: маржинальная прибыль / sold_cogs × 100.\n"
            "Сколько копеек прибыли приносит каждый рубль вложенный в закупку.\n"
            "100 % = удвоение, < 30 % — низкая, > 200 % — отличная."),
        # ─── Финансовые поля из wb_report_detail (только final mode) ─────
        KPI("commission_wb", "Комиссия WB", fin["commission"],
            prev_fin["commission"] if mode in ("final", "hybrid") else None,
            _pct_change(fin["commission"], prev_fin["commission"]) if mode in ("final", "hybrid") else None,
            "₽",
            "Комиссия WB + эквайринг — то что WB удерживает с каждого выкупа.\n"
            "Формула: Σ (retail_price_withdisc_rub − ppvz_for_pay) для Продаж − для Возвратов.\n"
            "Совпадает со столбцом «Комиссия WB и эквайринг» в WB-кабинете.\n"
            "Доступно только в Final режиме (источник — wb_report_detail)."),
        KPI("logistics_wb", "Логистика WB", fin["logistics"],
            prev_fin["logistics"] if mode in ("final", "hybrid") else None,
            _pct_change(fin["logistics"], prev_fin["logistics"]) if mode in ("final", "hybrid") else None,
            "₽",
            "Расходы на логистику WB за период (доставка до ПВЗ, обратная логистика).\n"
            "Формула: Σ wb_report_detail.delivery_rub.\n"
            "Совпадает со столбцом «Логистика» в WB-кабинете.\n"
            "Доступно только в Final режиме."),
        KPI("storage_wb", "Хранение WB", fin["storage"],
            prev_fin["storage"] if mode in ("final", "hybrid") else None,
            _pct_change(fin["storage"], prev_fin["storage"]) if mode in ("final", "hybrid") else None,
            "₽",
            "Плата за хранение товара на FBO-складах WB.\n"
            "Формула: Σ wb_report_detail.storage_fee.\n"
            "Совпадает со столбцом «Хранение» в WB-кабинете.\n"
            "Доступно только в Final режиме."),
        KPI("payout_to_account", "Итого к оплате", fin["payout_to_account"],
            prev_fin["payout_to_account"] if mode in ("final", "hybrid") else None,
            _pct_change(fin["payout_to_account"], prev_fin["payout_to_account"]) if mode in ("final", "hybrid") else None,
            "₽",
            "«Итого к оплате» (терминология TrueStats; ранее «Деньги на счёт») — "
            "деньги, которые WB реально переведёт на расчётный счёт за период.\n"
            "Формула: ppvz_net − логистика − хранение − штрафы − удержания + доплаты.\n"
            "Совпадает со строкой «Итог по товарам» в WB-кабинете.\n"
            "Это «то, что физически придёт на банк» — не путать с маржой и не путать с чистой выручкой.\n"
            "Доступно только в Final режиме."),
        KPI("contribution_margin", "Маржа без операционных расходов",
            contribution_margin, prev_contribution_margin,
            _pct_change(contribution_margin, prev_contribution_margin), "₽",
            "Контрибуционная маржа — прибыль ДО операционных и фиксированных расходов.\n"
            "Формула: Выручка net − Себестоимость − WB-удержания (комиссия + логистика + "
            "хранение + эквайринг + штрафы + удержания) − Реклама (WB + внешний маркетинг).\n"
            "НЕ включает: OPEX (зарплаты/аренда), фиксированные расходы, налоги, НДС.\n"
            "Берётся из pnl_builder.profit_from_sales (gross_profit − commercial_expenses)."),
        KPI("contribution_margin_pct", "Маржа без OPEX, %",
            contribution_margin_pct, prev_contribution_margin_pct,
            _pct_change(contribution_margin_pct, prev_contribution_margin_pct), "%",
            "Контрибуционная маржа в % от чистой выручки (после НДС).\n"
            "Формула: contribution_margin / revenue_after_vat × 100.\n"
            "Норма: 10-30 %; если ниже — операционные расходы (OPEX + налоги) могут увести в минус."),
        KPI("net_profit", "Чистая прибыль", net_profit, prev_net_profit,
            _pct_change(net_profit, prev_net_profit), "₽",
            "Финальная прибыль компании после ВСЕХ расходов:\n"
            "  + Чистая выручка (после WB-комиссии)\n"
            "  − Логистика, хранение, штрафы, удержания, эквайринг\n"
            "  − COGS (себестоимость проданных товаров)\n"
            "  − Реклама (WB advert + внешний маркетинг)\n"
            "  − OPEX (зарплаты, аренда, бухгалтерия и т.д.)\n"
            "  − Налоги и НДС (по timeline-ставкам)\n"
            "  − fixed_costs/30 (постоянные расходы pro-rata)\n\n"
            "Совпадает со строкой PROFIT на странице P&L за тот же период.\n"
            "Источник всегда wb_report_detail (не зависит от режима Preliminary/Final).\n"
            "Для manager scope (свой бренд) — contribution margin (без OPEX/налогов)."),
        # Stocks are a current snapshot (no historical series yet) — show only current.
        KPI("stock_units", "Остатки (шт)", stocks["stock_units"], None, None, "шт",
            "Сколько единиц товара сейчас на складах WB (последний snapshot).\n"
            "Источник: wb_stocks (FBO + FBS объединённо). Обновляется 2 раза в день."),
        KPI("stock_value", "Остатки в COGS", stocks["stock_value_at_cogs"], None, None, "₽",
            "Стоимость остатков в закупочных ценах (current COGS × qty).\n"
            "Это «замороженный капитал» в товарах на складе."),
    ]

    return {
        "mode": mode,
        "period": {
            "key": period.key,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "prev_start": period.prev_start.isoformat(),
            "prev_end": period.prev_end.isoformat(),
        },
        "kpis": [k.to_dict() for k in kpis],
    }


async def _sold_units_and_cogs(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    cogs_map: dict[int, float],
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
) -> tuple[float, float]:
    stmt = (
        select(
            WbSale.nm_id,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    nm_sub = _nm_id_subq(brands, nm_ids)
    if nm_sub is not None:
        stmt = stmt.where(WbSale.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    units = sum(int(r.units or 0) for r in rows)
    cogs = sum(int(r.units or 0) * cogs_map.get(int(r.nm_id), 0.0) for r in rows)
    return float(units), float(cogs)


async def _ad_cost_by_day(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    nm_sub: Any | None,
) -> dict[date, float]:
    """Daily WB ad spend over [start, end). Brand-scoped if nm_sub given."""
    stmt = (
        select(
            WbAdStatsDaily.stat_date.label("day"),
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
        )
        .where(
            WbAdStatsDaily.stat_date >= start.date(),
            WbAdStatsDaily.stat_date < end.date(),
        )
        .group_by(WbAdStatsDaily.stat_date)
    )
    if nm_sub is not None:
        stmt = stmt.where(WbAdStatsDaily.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    return {r.day: _f(r.ad_cost) for r in rows}


async def revenue_timeseries(
    session: AsyncSession,
    days: int = 30,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    mode: Mode = "preliminary",
    reporting_mode: ReportingMode = "operational",
) -> list[dict[str, Any]]:
    """Per-day revenue + orders + ad_cost.

    `reporting_mode='financial'` (только для mode='final') группирует по rr_dt
    вместо sale_dt — для бухгалтерской сверки. Для preliminary параметр
    игнорируется (orders/sales без аналога rr_dt).
    """
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    start = end - timedelta(days=days)

    nm_sub = _nm_id_subq(brands, nm_ids)
    ad_by_day = await _ad_cost_by_day(session, start, end, nm_sub)

    if mode == "final":
        is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
        is_compensation = WbReportDetail.supplier_oper_name.in_(_COMPENSATION_NAMES)
        revenue_field = func.coalesce(
            WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
        )
        # operational: group_by date_trunc('day', sale_dt) — datetime column.
        # financial:   group_by rr_dt (уже Date, кастить не надо).
        if reporting_mode == "financial":
            bucket = WbReportDetail.rr_dt.label("day")
        else:
            bucket = func.date_trunc("day", WbReportDetail.sale_dt).label("day")
        stmt = (
            select(
                bucket,
                func.coalesce(
                    func.sum(case((is_sale, revenue_field), else_=0))
                    - func.sum(case((is_compensation, WbReportDetail.ppvz_for_pay), else_=0)),
                    0,
                ).label("revenue"),
                func.coalesce(
                    func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0
                ).label("orders"),
            )
            .where(*_rd_period_predicates(start, end, reporting_mode))
            .group_by(bucket)
            .order_by(bucket)
        )
        if nm_sub is not None:
            stmt = stmt.where(WbReportDetail.nm_id.in_(nm_sub))
        rows = (await session.execute(stmt)).all()
        return [
            {
                "date": r.day.date().isoformat() if hasattr(r.day, "date") else r.day.isoformat(),
                "revenue": _f(r.revenue),
                "orders": int(r.orders or 0),
                "ad_cost": ad_by_day.get(
                    r.day.date() if hasattr(r.day, "date") else r.day, 0.0
                ),
            }
            for r in rows
        ]

    bucket = func.date_trunc("day", WbOrder.order_dt).label("day")
    # preliminary: orders feed, exclude cancelled (matches WB cabinet semantics).
    stmt = (
        select(
            bucket,
            func.coalesce(
                func.sum(
                    case(
                        (WbOrder.is_cancel, 0),
                        else_=WbOrder.total_price * (1 - WbOrder.discount_percent / 100),
                    )
                ),
                0,
            ).label("revenue"),
            func.coalesce(
                func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0
            ).label("orders"),
        )
        .where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
        .group_by(bucket)
        .order_by(bucket)
    )
    if nm_sub is not None:
        stmt = stmt.where(WbOrder.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    return [
        {
            "date": r.day.date().isoformat(),
            "revenue": _f(r.revenue),
            "orders": int(r.orders or 0),
            "ad_cost": ad_by_day.get(r.day.date(), 0.0),
        }
        for r in rows
    ]


async def top_skus(
    session: AsyncSession,
    period_or_key: "PeriodKey | Period",
    by: str = "revenue",
    limit: int = 5,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    mode: Mode = "preliminary",
    order: str = "desc",
    reporting_mode: ReportingMode = "operational",
) -> list[dict[str, Any]]:
    """Top SKUs.

    `reporting_mode` влияет только на mode='final' (период по sale_dt vs rr_dt).
    Для preliminary остаётся wb_orders.order_dt — игнорируется.
    """
    period = (
        period_or_key if isinstance(period_or_key, Period) else get_period(period_or_key)
    )
    cogs_map = await _latest_cogs_map(session, brands=brands, nm_ids=nm_ids)
    top_nm_sub = _nm_id_subq(brands, nm_ids)

    if mode == "final":
        is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
        is_return = WbReportDetail.supplier_oper_name.in_(_RETURN_NAMES)
        is_compensation = WbReportDetail.supplier_oper_name.in_(_COMPENSATION_NAMES)
        revenue_field = func.coalesce(
            WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
        )
        top_stmt = (
            select(
                WbReportDetail.nm_id,
                func.coalesce(
                    func.sum(case((is_sale, revenue_field), else_=0))
                    - func.sum(case((is_return, revenue_field), else_=0))
                    - func.sum(case((is_compensation, WbReportDetail.ppvz_for_pay), else_=0)),
                    0,
                ).label("revenue"),
                func.coalesce(
                    func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0
                ).label("orders"),
            )
            .where(
                *_rd_period_predicates(period.start, period.end, reporting_mode),
                WbReportDetail.nm_id.is_not(None),
            )
            .group_by(WbReportDetail.nm_id)
        )
        if top_nm_sub is not None:
            top_stmt = top_stmt.where(WbReportDetail.nm_id.in_(top_nm_sub))
        rows = (await session.execute(top_stmt)).all()
    else:
        top_stmt = (
            select(
                WbOrder.nm_id,
                func.coalesce(
                    func.sum(WbOrder.total_price * (1 - WbOrder.discount_percent / 100)), 0
                ).label("revenue"),
                func.count(WbOrder.srid).label("orders"),
            )
            .where(
                WbOrder.order_dt >= period.start,
                WbOrder.order_dt < period.end,
                WbOrder.is_cancel.is_(False),
            )
            .group_by(WbOrder.nm_id)
        )
        if top_nm_sub is not None:
            top_stmt = top_stmt.where(WbOrder.nm_id.in_(top_nm_sub))
        rows = (await session.execute(top_stmt)).all()
    products = {p.nm_id: p for p in (await session.execute(select(Product))).scalars().all()}

    items = []
    for r in rows:
        nm = int(r.nm_id)
        rev = _f(r.revenue)
        orders = int(r.orders or 0)
        cogs = cogs_map.get(nm, 0.0) * orders
        margin = rev - cogs
        margin_pct = (margin / rev * 100.0) if rev > 0 else 0.0
        roi = (margin / cogs * 100.0) if cogs > 0 else 0.0
        prod = products.get(nm)
        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": prod.brand if prod else None,
                "revenue": rev,
                "orders": orders,
                # margin_estimate — legacy alias, оставлен для back-compat.
                "margin_estimate": margin,
                "margin": margin,
                "margin_pct": margin_pct,
                "roi": roi,
            }
        )
    reverse = order != "asc"
    if by == "margin":
        items.sort(key=lambda x: x["margin"], reverse=reverse)
    else:
        items.sort(key=lambda x: x["revenue"], reverse=reverse)
    return items[:limit]
