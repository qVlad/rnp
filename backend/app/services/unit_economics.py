"""Per-SKU unit economics: revenue, commission, ad spend, COGS, margin, days-to-stockout."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def _latest_cogs(session: AsyncSession) -> dict[int, dict[str, float]]:
    rows = (
        await session.execute(
            select(
                Cogs.nm_id,
                Cogs.cost_rub,
                Cogs.packaging_rub,
                Cogs.fulfillment_rub,
                Cogs.valid_from,
            ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
        )
    ).all()
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        nm = int(r.nm_id)
        if nm in out:
            continue
        out[nm] = {
            "cost": _f(r.cost_rub),
            "pack": _f(r.packaging_rub),
            "ful": _f(r.fulfillment_rub),
        }
    return out


async def build_unit_economics(
    session: AsyncSession,
    *,
    days_back: int = 30,
    include_archived: bool = False,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    sales_stmt = (
        select(
            WbSale.nm_id,
            func.count().label("rows"),
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
            func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)).label("for_pay"),
            func.sum(case((WbSale.is_return, 0), else_=WbSale.price_with_disc)).label(
                "price_with_disc"
            ),
            func.avg(WbSale.commission_percent).label("commission_pct"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_rows = (await session.execute(sales_stmt)).all()

    # Real commission % per nm_id from wb_report_detail (sales-side).
    # WbSale.commission_percent comes from /sales feed and is often 0 in
    # production for some seller token types. report_detail is the source
    # of truth: commission_pct = (retail_with_disc − ppvz_for_pay) / retail × 100.
    rd_revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    rd_is_sale = WbReportDetail.supplier_oper_name == "Продажа"
    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            func.coalesce(func.sum(case((rd_is_sale, rd_revenue_field), else_=0)), 0).label("rev"),
            func.coalesce(
                func.sum(case((rd_is_sale, WbReportDetail.ppvz_for_pay), else_=0)), 0
            ).label("ppvz"),
        )
        .where(WbReportDetail.sale_dt >= start, WbReportDetail.sale_dt < end)
        .group_by(WbReportDetail.nm_id)
    )
    if nm_filter is not None:
        rd_stmt = rd_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    rd_rows = (await session.execute(rd_stmt)).all()
    commission_by_nm: dict[int, float] = {}
    for r in rd_rows:
        rev = _f(r.rev)
        if rev > 0:
            commission_by_nm[int(r.nm_id)] = (rev - _f(r.ppvz)) / rev * 100

    orders_stmt = (
        select(
            WbOrder.nm_id,
            func.count().label("orders"),
            func.coalesce(
                func.sum(WbOrder.total_price * (1 - WbOrder.discount_percent / 100)), 0
            ).label("revenue"),
        )
        .where(
            WbOrder.order_dt >= start,
            WbOrder.order_dt < end,
            WbOrder.is_cancel.is_(False),
        )
        .group_by(WbOrder.nm_id)
    )
    if nm_filter is not None:
        orders_stmt = orders_stmt.where(WbOrder.nm_id.in_(nm_filter))
    orders_rows = (await session.execute(orders_stmt)).all()
    orders_by_nm = {int(r.nm_id): {"orders": int(r.orders), "revenue": _f(r.revenue)} for r in orders_rows}

    ad_stmt = (
        select(
            WbAdStatsDaily.nm_id,
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
            func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("ad_orders"),
        )
        .where(
            WbAdStatsDaily.stat_date >= start.date(),
            WbAdStatsDaily.stat_date < end.date() + timedelta(days=1),
            WbAdStatsDaily.nm_id.isnot(None),
        )
        .group_by(WbAdStatsDaily.nm_id)
    )
    if nm_filter is not None:
        ad_stmt = ad_stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    ad_rows = (await session.execute(ad_stmt)).all()
    ad_by_nm = {int(r.nm_id): {"ad_cost": _f(r.ad_cost), "ad_orders": int(r.ad_orders)} for r in ad_rows}

    # External (off-WB) marketing costs by SKU.
    ext_stmt = (
        select(
            ExternalAdCost.nm_id,
            func.coalesce(func.sum(ExternalAdCost.amount), 0).label("ext_cost"),
        )
        .where(
            ExternalAdCost.spend_date >= start.date(),
            ExternalAdCost.spend_date < end.date() + timedelta(days=1),
            ExternalAdCost.nm_id.isnot(None),
        )
        .group_by(ExternalAdCost.nm_id)
    )
    if nm_filter is not None:
        ext_stmt = ext_stmt.where(ExternalAdCost.nm_id.in_(nm_filter))
    ext_rows = (await session.execute(ext_stmt)).all()
    ext_ad_by_nm: dict[int, float] = {int(r.nm_id): _f(r.ext_cost) for r in ext_rows}

    # Brand-level external marketing (nm_id=NULL) — distribute pro-rata by revenue.
    brand_ext_total = _f(
        (
            await session.execute(
                select(func.coalesce(func.sum(ExternalAdCost.amount), 0)).where(
                    ExternalAdCost.spend_date >= start.date(),
                    ExternalAdCost.spend_date < end.date() + timedelta(days=1),
                    ExternalAdCost.nm_id.is_(None),
                )
            )
        ).scalar_one()
    )

    latest_dt = select(func.max(WbStockSnapshot.snapshot_dt)).scalar_subquery()
    stock_stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
        )
        .where(WbStockSnapshot.snapshot_dt == latest_dt)
        .group_by(WbStockSnapshot.nm_id)
    )
    if nm_filter is not None:
        stock_stmt = stock_stmt.where(WbStockSnapshot.nm_id.in_(nm_filter))
    stock_rows = (await session.execute(stock_stmt)).all()
    stock_by_nm = {int(r.nm_id): int(r.qty or 0) for r in stock_rows}

    # Use the historical cost lookup so old sales get the cost that was valid then.
    # Lazy import to avoid circular module imports.
    from app.services.pnl_builder import build_cogs_lookup, cost_for_date  # noqa: WPS433

    cogs_lookup = await build_cogs_lookup(session)
    midpoint = (start + (end - start) / 2).date()  # representative date for the window
    products_stmt = select(Product)
    if brands is not None:
        products_stmt = products_stmt.where(Product.brand.in_(list(brands)))
    all_products = (await session.execute(products_stmt)).scalars().all()
    products = {p.nm_id: p for p in all_products}
    archived_nm_ids: set[int] = (
        set() if include_archived else {p.nm_id for p in all_products if p.is_archived}
    )

    # First pass — gather per-SKU revenue so we can distribute brand-level
    # external ad spend pro-rata by revenue afterwards.
    nm_set = (
        set(orders_by_nm.keys())
        | set(int(r.nm_id) for r in sales_rows)
        | set(stock_by_nm.keys())
    )
    if archived_nm_ids:
        nm_set -= archived_nm_ids
    revenue_by_nm: dict[int, float] = {
        nm: orders_by_nm.get(nm, {}).get("revenue", 0.0) for nm in nm_set
    }
    total_revenue = sum(revenue_by_nm.values())

    def brand_share_for(nm: int) -> float:
        if total_revenue <= 0 or brand_ext_total <= 0:
            return 0.0
        return brand_ext_total * (revenue_by_nm.get(nm, 0.0) / total_revenue)

    items: list[dict[str, Any]] = []
    for nm in nm_set:
        prod = products.get(nm)
        sale = next((r for r in sales_rows if int(r.nm_id) == nm), None)
        units_sold = int(sale.units or 0) if sale else 0
        for_pay = _f(sale.for_pay) if sale else 0.0
        avg_price = (
            _f(sale.price_with_disc) / max(1, int(sale.rows or 0)) if sale and sale.rows else 0.0
        )
        # Prefer commission_pct calculated from wb_report_detail (real WB %).
        # Fall back to wb_sales.commission_percent for older periods where
        # report_detail hasn't arrived yet.
        commission_pct = commission_by_nm.get(nm) or (_f(sale.commission_pct) if sale else 0.0)

        orders = orders_by_nm.get(nm, {}).get("orders", 0)
        revenue = revenue_by_nm.get(nm, 0.0)

        ad_cost = ad_by_nm.get(nm, {}).get("ad_cost", 0.0)
        ext_per_sku = ext_ad_by_nm.get(nm, 0.0)
        ext_brand = brand_share_for(nm)
        ext_total = ext_per_sku + ext_brand
        marketing_total = ad_cost + ext_total
        per_order_marketing = marketing_total / orders if orders > 0 else 0.0

        unit_cogs = cost_for_date(cogs_lookup, nm, midpoint)

        unit_revenue_net = (for_pay / units_sold) if units_sold > 0 else 0.0
        unit_margin = unit_revenue_net - unit_cogs - per_order_marketing
        unit_margin_pct = (unit_margin / unit_revenue_net * 100) if unit_revenue_net > 0 else 0.0
        roi = (unit_margin / unit_cogs * 100) if unit_cogs > 0 else 0.0
        # DRR (доля рекламных расходов) — total marketing / revenue
        drr_pct = (marketing_total / revenue * 100) if revenue > 0 else 0.0

        # days-to-stockout from last 14d sales velocity
        velocity_units = await _velocity_14d(session, nm)
        stock = stock_by_nm.get(nm, 0)
        dts = round(stock / velocity_units, 1) if velocity_units > 0 else None

        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": prod.brand if prod else None,
                "photo_url": prod.photo_url if prod else None,
                "is_archived": bool(prod.is_archived) if prod else False,
                "orders": orders,
                "units_sold": units_sold,
                "revenue": revenue,
                "for_pay": for_pay,
                "avg_price": round(avg_price, 2),
                "commission_pct": round(commission_pct, 2),
                "ad_cost": round(ad_cost, 2),
                "external_ad_cost": round(ext_total, 2),
                "ad_per_order": round(per_order_marketing, 2),
                "drr_pct": round(drr_pct, 2),
                "cogs_unit": round(unit_cogs, 2),
                "margin_unit": round(unit_margin, 2),
                "margin_pct": round(unit_margin_pct, 2),
                "roi_pct": round(roi, 2),
                "stock": stock,
                "days_to_stockout": dts,
            }
        )

    items.sort(key=lambda x: x["revenue"], reverse=True)
    return {"days_back": days_back, "items": items}


async def _velocity_14d(session: AsyncSession, nm_id: int) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    row = (
        await session.execute(
            select(func.coalesce(func.sum(case((WbSale.is_return, -1), else_=1)), 0)).where(
                WbSale.nm_id == nm_id,
                WbSale.sale_dt >= start,
                WbSale.sale_dt < end,
            )
        )
    ).scalar_one()
    return float(row or 0) / 14.0
