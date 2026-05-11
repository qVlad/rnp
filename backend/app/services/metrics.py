"""Compute dashboard KPIs.

The dashboard uses operational data (orders + sales + ad stats) for the current
window — these are available with ~30 minute lag. Historical P&L uses the
report-detail table (1-2 day lag); see `pnl_builder.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Literal

from app.db.models import (
    Cogs,
    ExternalAdCost,
    Product,
    WbAdStatsDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.periods import Period, PeriodKey, get_period

Mode = Literal["preliminary", "final"]
# Final-mode aggregations match the WB seller cabinet «Выкупы» / «Возвраты»
# columns 1:1. Two pieces matter:
#   1) Filter Продажа / Возврат on `supplier_oper_name` (not doc_type_name).
#      doc_type=Продажа also catches «Возмещение за выдачу...», «Программа
#      лояльности», «Добровольная компенсация», which WB cabinet shows in its
#      own buckets (Потери/подмены, Лояльность) — not in «Выкупы».
#   2) WB further subtracts the ppvz_for_pay of «Добровольная компенсация при
#      возврате» from «Выкупы» (it counts as a buyback fee). Mirror that.
_SALE_NAMES = ("Продажа", "продажа")
_RETURN_NAMES = ("Возврат", "возврат")
_COMPENSATION_NAMES = ("Добровольная компенсация при возврате",)

D0 = Decimal("0")


def _nm_id_subq(brands: set[str] | None):
    """Sub-select of nm_ids belonging to the brand whitelist.

    `None` ⇒ caller should not apply any filter (unrestricted role).
    Empty set ⇒ caller will produce zero rows by design (manager with no
    assignments).
    """
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


async def _orders_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
) -> dict[str, float]:
    # NB: revenue_gross and orders both EXCLUDE cancelled orders. WB seller
    # cabinet does the same — including cancels here would double-count.
    # `cancellations` is exposed separately for transparency.
    stmt = select(
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0
        ).label("orders"),
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0
        ).label("orders_active"),
        func.coalesce(
            func.sum(
                case(
                    (WbOrder.is_cancel, 0),
                    else_=WbOrder.total_price * (1 - WbOrder.discount_percent / 100),
                )
            ),
            0,
        ).label("revenue_gross"),
        func.coalesce(
            func.sum(case((WbOrder.is_cancel, 1), else_=0)), 0
        ).label("cancellations"),
    ).where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
    sub = _nm_id_subq(brands)
    if sub is not None:
        stmt = stmt.where(WbOrder.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    return {
        "orders": _f(row.orders),
        "orders_active": _f(row.orders_active),
        "revenue_gross": _f(row.revenue_gross),
        "cancellations": _f(row.cancellations),
    }


async def _sales_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
) -> dict[str, float]:
    stmt = select(
        func.coalesce(
            func.sum(case((WbSale.is_return, 0), else_=1)), 0
        ).label("sales"),
        func.coalesce(
            func.sum(case((WbSale.is_return, 1), else_=0)), 0
        ).label("returns"),
        func.coalesce(
            func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)), 0
        ).label("for_pay_net"),
        func.coalesce(
            func.sum(case((WbSale.is_return, WbSale.for_pay), else_=0)), 0
        ).label("for_pay_returns"),
    ).where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
    sub = _nm_id_subq(brands)
    if sub is not None:
        stmt = stmt.where(WbSale.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    return {
        "sales": _f(row.sales),
        "returns": _f(row.returns),
        "for_pay_net": _f(row.for_pay_net),
        "for_pay_returns": _f(row.for_pay_returns),
    }


async def _final_orders_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
) -> dict[str, float]:
    """Final-mode orders: from wb_report_detail by sale_dt.

    Filter by **sale_dt** (date of physical buyout/return), not `rr_dt`.
    The WB seller cabinet groups «Выкупы»/«Возвраты» by sale_dt — a return
    that happens this week for a sale from previous week is shown in the
    PREVIOUS week's bucket. Filtering by rr_dt would mix them.

    `report_detail` doesn't model "cancelled order" — only Продажа / Возврат
    rows. So orders = sales count, cancellations = 0.
    """
    rd_start, rd_end = start.date(), end.date()
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
    ).where(
        WbReportDetail.sale_dt >= datetime.combine(rd_start, datetime.min.time(), tzinfo=timezone.utc),
        WbReportDetail.sale_dt < datetime.combine(rd_end, datetime.min.time(), tzinfo=timezone.utc),
    )
    sub = _nm_id_subq(brands)
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
) -> dict[str, float]:
    """Final-mode sales: count and net payout from wb_report_detail.

    Filtered on supplier_oper_name (not doc_type_name) — same logic as
    _final_orders_aggregate.
    """
    rd_start, rd_end = start.date(), end.date()
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
    ).where(
        WbReportDetail.sale_dt >= datetime.combine(rd_start, datetime.min.time(), tzinfo=timezone.utc),
        WbReportDetail.sale_dt < datetime.combine(rd_end, datetime.min.time(), tzinfo=timezone.utc),
    )
    sub = _nm_id_subq(brands)
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
    rd_start, rd_end = start.date(), end.date()
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
    ).where(
        WbReportDetail.sale_dt >= datetime.combine(rd_start, datetime.min.time(), tzinfo=timezone.utc),
        WbReportDetail.sale_dt < datetime.combine(rd_end, datetime.min.time(), tzinfo=timezone.utc),
    )
    sub = _nm_id_subq(brands)
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
) -> tuple[float, float]:
    """Net sold quantity and COGS from wb_report_detail (sales − returns).

    Filtered by sale_dt and supplier_oper_name to match the WB cabinet's
    «Выкупы» and «Возвраты» buckets.
    """
    rd_start, rd_end = start.date(), end.date()
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
        .where(
            WbReportDetail.sale_dt >= datetime.combine(rd_start, datetime.min.time(), tzinfo=timezone.utc),
            WbReportDetail.sale_dt < datetime.combine(rd_end, datetime.min.time(), tzinfo=timezone.utc),
        )
        .group_by(WbReportDetail.nm_id)
    )
    sub = _nm_id_subq(brands)
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
    sub = _nm_id_subq(brands)
    if sub is not None:
        stmt = stmt.where(WbAdStatsDaily.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    wb_ad_cost = _f(row.ad_cost)

    # External (off-WB) ad costs — bloggers, infographics, banners.
    ext_stmt = select(
        func.coalesce(func.sum(ExternalAdCost.amount), 0).label("ext_cost")
    ).where(
        ExternalAdCost.spend_date >= start.date(),
        ExternalAdCost.spend_date < end.date(),
    )
    if sub is not None:
        # Manager scope: only nm_id-attributed external ads. Brand-level
        # rows (nm_id IS NULL) are not split per-brand.
        ext_stmt = ext_stmt.where(ExternalAdCost.nm_id.in_(sub))
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
    session: AsyncSession, brands: set[str] | None = None
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
    nm_sub = _nm_id_subq(brands)
    if nm_sub is not None:
        stmt = stmt.where(WbStockSnapshot.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()

    total_units = float(sum(_f(r.qty) for r in rows))

    cogs_map = await _latest_cogs_map(session, brands=brands)
    total_value = float(
        sum(_f(r.qty) * cogs_map.get(int(r.nm_id), 0.0) for r in rows)
    )
    return {"stock_units": total_units, "stock_value_at_cogs": total_value}


async def _latest_cogs_map(
    session: AsyncSession, brands: set[str] | None = None
) -> dict[int, float]:
    stmt = select(
        Cogs.nm_id,
        Cogs.cost_rub,
        Cogs.packaging_rub,
        Cogs.fulfillment_rub,
        Cogs.valid_from,
    ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
    nm_sub = _nm_id_subq(brands)
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


async def compute_dashboard(
    session: AsyncSession,
    period_or_key: "PeriodKey | Period",
    brands: set[str] | None = None,
    mode: Mode = "preliminary",
) -> dict[str, Any]:
    """Build dashboard KPIs.

    `mode='preliminary'` (default) — orders/sales come from wb_orders/wb_sales,
    fast-updating but with cancellation noise on the right edge of the period.

    `mode='final'` — read from wb_report_detail by rr_dt. Final WB numbers,
    matches the WB seller cabinet exactly. Updated weekly, ~14 day lag for the
    most recent week.
    """
    period: Period = (
        period_or_key if isinstance(period_or_key, Period) else get_period(period_or_key)
    )
    if mode == "final":
        orders_fn = _final_orders_aggregate
        sales_fn = _final_sales_aggregate
        sold_fn = _final_sold_units_and_cogs
    else:
        orders_fn = _orders_aggregate
        sales_fn = _sales_aggregate
        sold_fn = _sold_units_and_cogs

    curr_orders = await orders_fn(session, period.start, period.end, brands)
    prev_orders = await orders_fn(session, period.prev_start, period.prev_end, brands)
    curr_sales = await sales_fn(session, period.start, period.end, brands)
    prev_sales = await sales_fn(session, period.prev_start, period.prev_end, brands)
    curr_ad = await _ad_aggregate(session, period.start, period.end, brands)
    prev_ad = await _ad_aggregate(session, period.prev_start, period.prev_end, brands)
    stocks = await _stocks_aggregate(session, brands)

    curr = _compute_window_kpis(curr_orders, curr_sales, curr_ad)
    prev = _compute_window_kpis(prev_orders, prev_sales, prev_ad)

    cogs_map = await _latest_cogs_map(session, brands=brands)
    sold_units, sold_cogs = await sold_fn(
        session, period.start, period.end, cogs_map, brands=brands
    )
    _, prev_sold_cogs = await sold_fn(
        session, period.prev_start, period.prev_end, cogs_map, brands=brands
    )
    # Финансовые поля из wb_report_detail доступны только в final mode.
    if mode == "final":
        fin = await _final_finance_aggregate(session, period.start, period.end, brands)
        prev_fin = await _final_finance_aggregate(session, period.prev_start, period.prev_end, brands)
    else:
        fin = _empty_finance()
        prev_fin = _empty_finance()

    # Чистая прибыль (full P&L profit) — нужен build_pnl. Он использует
    # wb_report_detail независимо от режима дашборда, так что результат
    # одинаков для preliminary/final. Lazy import чтобы не было кругового
    # импорта (pnl_builder сам импортирует metrics в reconciliation).
    from app.services.pnl_builder import build_pnl  # noqa: WPS433

    pnl_from = period.start.date()
    pnl_to = (period.end - timedelta(days=1)).date()
    pnl_curr = await build_pnl(
        session, date_from=pnl_from, date_to=pnl_to, granularity="month", brands=brands
    )
    pnl_prev_from = period.prev_start.date()
    pnl_prev_to = (period.prev_end - timedelta(days=1)).date()
    pnl_prev = await build_pnl(
        session, date_from=pnl_prev_from, date_to=pnl_prev_to, granularity="month", brands=brands
    )
    net_profit = _f(pnl_curr.get("totals", {}).get("profit", 0))
    prev_net_profit = _f(pnl_prev.get("totals", {}).get("profit", 0))

    margin_value = curr["revenue_net"] - sold_cogs - curr["ad_cost"]
    margin_pct = (margin_value / curr["revenue_net"] * 100) if curr["revenue_net"] > 0 else 0.0
    prev_margin_value = prev["revenue_net"] - prev_sold_cogs - prev["ad_cost"]
    prev_margin_pct = (
        (prev_margin_value / prev["revenue_net"] * 100) if prev["revenue_net"] > 0 else 0.0
    )
    # ROI / Рентабельность по COGS — сколько прибыли с каждого вложенного рубля себестоимости
    roi = (margin_value / sold_cogs * 100) if sold_cogs > 0 else 0.0
    prev_roi = (prev_margin_value / prev_sold_cogs * 100) if prev_sold_cogs > 0 else 0.0

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
        KPI("revenue_net", "Чистая выручка", curr["revenue_net"], prev["revenue_net"],
            _pct_change(curr["revenue_net"], prev["revenue_net"]), "₽",
            "Выплата селлеру после WB-комиссии (до логистики/хранения/налогов).\n"
            f"Σ ppvz_for_pay (Продажи − Возвраты) за период.\nИсточник: {src_orders}."),
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
            prev_fin["commission"] if mode == "final" else None,
            _pct_change(fin["commission"], prev_fin["commission"]) if mode == "final" else None,
            "₽",
            "Комиссия WB + эквайринг — то что WB удерживает с каждого выкупа.\n"
            "Формула: Σ (retail_price_withdisc_rub − ppvz_for_pay) для Продаж − для Возвратов.\n"
            "Совпадает со столбцом «Комиссия WB и эквайринг» в WB-кабинете.\n"
            "Доступно только в Final режиме (источник — wb_report_detail)."),
        KPI("logistics_wb", "Логистика WB", fin["logistics"],
            prev_fin["logistics"] if mode == "final" else None,
            _pct_change(fin["logistics"], prev_fin["logistics"]) if mode == "final" else None,
            "₽",
            "Расходы на логистику WB за период (доставка до ПВЗ, обратная логистика).\n"
            "Формула: Σ wb_report_detail.delivery_rub.\n"
            "Совпадает со столбцом «Логистика» в WB-кабинете.\n"
            "Доступно только в Final режиме."),
        KPI("storage_wb", "Хранение WB", fin["storage"],
            prev_fin["storage"] if mode == "final" else None,
            _pct_change(fin["storage"], prev_fin["storage"]) if mode == "final" else None,
            "₽",
            "Плата за хранение товара на FBO-складах WB.\n"
            "Формула: Σ wb_report_detail.storage_fee.\n"
            "Совпадает со столбцом «Хранение» в WB-кабинете.\n"
            "Доступно только в Final режиме."),
        KPI("payout_to_account", "Деньги на счёт", fin["payout_to_account"],
            prev_fin["payout_to_account"] if mode == "final" else None,
            _pct_change(fin["payout_to_account"], prev_fin["payout_to_account"]) if mode == "final" else None,
            "₽",
            "Деньги, которые WB реально переведёт на расчётный счёт за период.\n"
            "Формула: ppvz_net − логистика − хранение − штрафы − удержания + доплаты.\n"
            "Совпадает со строкой «Итог по товарам» в WB-кабинете.\n"
            "Это «то, что физически придёт на банк» — не путать с маржой и не путать с чистой выручкой.\n"
            "Доступно только в Final режиме."),
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
) -> tuple[float, float]:
    stmt = (
        select(
            WbSale.nm_id,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    nm_sub = _nm_id_subq(brands)
    if nm_sub is not None:
        stmt = stmt.where(WbSale.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    units = sum(int(r.units or 0) for r in rows)
    cogs = sum(int(r.units or 0) * cogs_map.get(int(r.nm_id), 0.0) for r in rows)
    return float(units), float(cogs)


async def revenue_timeseries(
    session: AsyncSession,
    days: int = 30,
    brands: set[str] | None = None,
    mode: Mode = "preliminary",
) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    start = end - timedelta(days=days)

    nm_sub = _nm_id_subq(brands)

    if mode == "final":
        bucket = func.date_trunc("day", WbReportDetail.sale_dt).label("day")
        is_sale = WbReportDetail.supplier_oper_name.in_(_SALE_NAMES)
        is_compensation = WbReportDetail.supplier_oper_name.in_(_COMPENSATION_NAMES)
        revenue_field = func.coalesce(
            WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
        )
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
            .where(WbReportDetail.sale_dt >= start, WbReportDetail.sale_dt < end)
            .group_by(bucket)
            .order_by(bucket)
        )
        if nm_sub is not None:
            stmt = stmt.where(WbReportDetail.nm_id.in_(nm_sub))
        rows = (await session.execute(stmt)).all()
        return [
            {"date": r.day.isoformat(), "revenue": _f(r.revenue), "orders": int(r.orders or 0)}
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
        {"date": r.day.date().isoformat(), "revenue": _f(r.revenue), "orders": int(r.orders or 0)}
        for r in rows
    ]


async def top_skus(
    session: AsyncSession,
    period_or_key: "PeriodKey | Period",
    by: str = "revenue",
    limit: int = 5,
    brands: set[str] | None = None,
    mode: Mode = "preliminary",
) -> list[dict[str, Any]]:
    period = (
        period_or_key if isinstance(period_or_key, Period) else get_period(period_or_key)
    )
    cogs_map = await _latest_cogs_map(session, brands=brands)
    top_nm_sub = _nm_id_subq(brands)

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
                WbReportDetail.sale_dt >= period.start,
                WbReportDetail.sale_dt < period.end,
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
        prod = products.get(nm)
        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "revenue": rev,
                "orders": orders,
                "margin_estimate": margin,
            }
        )
    if by == "margin":
        items.sort(key=lambda x: x["margin_estimate"], reverse=True)
    else:
        items.sort(key=lambda x: x["revenue"], reverse=True)
    return items[:limit]
