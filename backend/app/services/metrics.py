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
    Product,
    WbAdStatsDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.periods import Period, PeriodKey, get_period

Mode = Literal["preliminary", "final"]
_SALE_NAMES = ("Продажа", "продажа")
_RETURN_NAMES = ("Возврат", "возврат")

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": round(self.value, 2),
            "prev_value": round(self.prev_value, 2) if self.prev_value is not None else None,
            "change_pct": self.change_pct,
            "unit": self.unit,
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
    """Final-mode orders: from wb_report_detail by rr_dt.

    `report_detail` doesn't model "cancelled order" — only Продажа / Возврат rows.
    So orders = sales count, cancellations = 0. Revenue uses
    `retail_price_withdisc_rub` (price the buyer actually paid after WB SPP /
    promo discount) — that matches what the WB seller cabinet shows under
    «Продажи». Falls back to `retail_amount` for older rows where the field
    wasn't populated yet.
    """
    rd_start, rd_end = start.date(), end.date()
    revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    stmt = select(
        func.coalesce(
            func.sum(case((WbReportDetail.doc_type_name.in_(_SALE_NAMES), 1), else_=0)), 0
        ).label("orders"),
        func.coalesce(
            func.sum(
                case(
                    (WbReportDetail.doc_type_name.in_(_SALE_NAMES), revenue_field),
                    else_=0,
                )
            ),
            0,
        ).label("revenue_gross"),
    ).where(WbReportDetail.rr_dt >= rd_start, WbReportDetail.rr_dt < rd_end)
    sub = _nm_id_subq(brands)
    if sub is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    orders = _f(row.orders)
    return {
        "orders": orders,
        "orders_active": orders,
        "revenue_gross": _f(row.revenue_gross),
        "cancellations": 0.0,
    }


async def _final_sales_aggregate(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    brands: set[str] | None = None,
) -> dict[str, float]:
    """Final-mode sales: count and net payout from wb_report_detail."""
    rd_start, rd_end = start.date(), end.date()
    is_sale = WbReportDetail.doc_type_name.in_(_SALE_NAMES)
    is_return = WbReportDetail.doc_type_name.in_(_RETURN_NAMES)
    stmt = select(
        func.coalesce(func.sum(case((is_sale, 1), else_=0)), 0).label("sales"),
        func.coalesce(func.sum(case((is_return, 1), else_=0)), 0).label("returns"),
        func.coalesce(
            func.sum(case((is_sale, WbReportDetail.ppvz_for_pay), else_=0))
            - func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)),
            0,
        ).label("for_pay_net"),
        func.coalesce(
            func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)), 0
        ).label("for_pay_returns"),
    ).where(WbReportDetail.rr_dt >= rd_start, WbReportDetail.rr_dt < rd_end)
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


async def _final_sold_units_and_cogs(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    cogs_map: dict[int, float],
    brands: set[str] | None = None,
) -> tuple[float, float]:
    """Net sold quantity and COGS from wb_report_detail (sales − returns)."""
    rd_start, rd_end = start.date(), end.date()
    stmt = (
        select(
            WbReportDetail.nm_id,
            func.sum(
                case(
                    (WbReportDetail.doc_type_name.in_(_SALE_NAMES), WbReportDetail.quantity),
                    (WbReportDetail.doc_type_name.in_(_RETURN_NAMES), -WbReportDetail.quantity),
                    else_=0,
                )
            ).label("units"),
        )
        .where(WbReportDetail.rr_dt >= rd_start, WbReportDetail.rr_dt < rd_end)
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
    stmt = select(
        func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
        func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("ad_clicks"),
        func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("ad_views"),
        func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("ad_orders"),
    ).where(
        WbAdStatsDaily.stat_date >= start.date(),
        WbAdStatsDaily.stat_date < end.date() + timedelta(days=1),
    )
    sub = _nm_id_subq(brands)
    if sub is not None:
        stmt = stmt.where(WbAdStatsDaily.nm_id.in_(sub))
    row = (await session.execute(stmt)).one()
    return {
        "ad_cost": _f(row.ad_cost),
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
    # So the denominator must be ALL orders, not only non-cancelled.
    total_orders = orders_count + cancellations
    buyout = (sales_count - returns) / total_orders * 100 if total_orders > 0 else 0.0
    drr = ad_cost / revenue_gross * 100 if revenue_gross > 0 else 0.0
    return_rate = returns / sales_count * 100 if sales_count > 0 else 0.0

    return {
        "revenue_gross": revenue_gross,
        "revenue_net": revenue_net,
        "orders": orders_count,
        "sales": sales_count,
        "returns": returns,
        "ad_cost": ad_cost,
        "buyout_pct": buyout,
        "drr_pct": drr,
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
    margin_value = curr["revenue_net"] - sold_cogs - curr["ad_cost"]
    margin_pct = (margin_value / curr["revenue_net"] * 100) if curr["revenue_net"] > 0 else 0.0
    prev_margin_value = prev["revenue_net"] - prev_sold_cogs - prev["ad_cost"]
    prev_margin_pct = (
        (prev_margin_value / prev["revenue_net"] * 100) if prev["revenue_net"] > 0 else 0.0
    )

    kpis = [
        KPI("revenue_gross", "Выручка (gross)", curr["revenue_gross"], prev["revenue_gross"],
            _pct_change(curr["revenue_gross"], prev["revenue_gross"]), "₽"),
        KPI("revenue_net", "Чистая выручка", curr["revenue_net"], prev["revenue_net"],
            _pct_change(curr["revenue_net"], prev["revenue_net"]), "₽"),
        KPI("orders", "Заказы", curr["orders"], prev["orders"],
            _pct_change(curr["orders"], prev["orders"]), "шт"),
        KPI("buyout_pct", "Выкуп", curr["buyout_pct"], prev["buyout_pct"],
            _pct_change(curr["buyout_pct"], prev["buyout_pct"]), "%"),
        KPI("returns", "Возвраты", curr["returns"], prev["returns"],
            _pct_change(curr["returns"], prev["returns"]), "шт"),
        KPI("ad_cost", "Реклама (расход)", curr["ad_cost"], prev["ad_cost"],
            _pct_change(curr["ad_cost"], prev["ad_cost"]), "₽"),
        KPI("drr_pct", "ДРР", curr["drr_pct"], prev["drr_pct"],
            _pct_change(curr["drr_pct"], prev["drr_pct"]), "%"),
        KPI("margin", "Маржинальная прибыль", margin_value, prev_margin_value,
            _pct_change(margin_value, prev_margin_value), "₽"),
        KPI("margin_pct", "Маржа", margin_pct, prev_margin_pct,
            _pct_change(margin_pct, prev_margin_pct), "%"),
        # Stocks are a current snapshot (no historical series yet) — show only current.
        KPI("stock_units", "Остатки (шт)", stocks["stock_units"], None, None, "шт"),
        KPI("stock_value", "Остатки в COGS", stocks["stock_value_at_cogs"], None, None, "₽"),
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
        bucket = WbReportDetail.rr_dt.label("day")
        is_sale = WbReportDetail.doc_type_name.in_(_SALE_NAMES)
        revenue_field = func.coalesce(
            WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
        )
        stmt = (
            select(
                bucket,
                func.coalesce(
                    func.sum(case((is_sale, revenue_field), else_=0)), 0
                ).label("revenue"),
                func.coalesce(func.sum(case((is_sale, 1), else_=0)), 0).label("orders"),
            )
            .where(WbReportDetail.rr_dt >= start.date(), WbReportDetail.rr_dt < end.date())
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
        is_sale = WbReportDetail.doc_type_name.in_(_SALE_NAMES)
        is_return = WbReportDetail.doc_type_name.in_(_RETURN_NAMES)
        revenue_field = func.coalesce(
            WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
        )
        top_stmt = (
            select(
                WbReportDetail.nm_id,
                func.coalesce(
                    func.sum(case((is_sale, revenue_field), else_=0))
                    - func.sum(case((is_return, revenue_field), else_=0)),
                    0,
                ).label("revenue"),
                func.coalesce(func.sum(case((is_sale, 1), else_=0)), 0).label("orders"),
            )
            .where(
                WbReportDetail.rr_dt >= period.start.date(),
                WbReportDetail.rr_dt < period.end.date(),
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
