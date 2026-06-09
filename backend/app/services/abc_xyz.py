"""ABC + XYZ analysis of SKU performance.

ABC — distribution by share of value (revenue / profit / units / margin):
  A — top 80% (cumulative)
  B — next 15%
  C — last 5%
The thresholds are configurable but default matches the classic Pareto split.

XYZ — distribution by stability of demand using coefficient of variation
(CV = stddev / mean) computed over daily-bucketed series:
  X — CV < 0.10  (стабильный спрос)
  Y — 0.10–0.25  (предсказуемые колебания)
  Z — > 0.25     (нерегулярный)

The combination matrix (AX/AY/AZ/.../CZ) is the standard tool for stocking
strategy: AX/AY = always in stock, BZ/CZ = either drop or pre-order on demand.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cogs, Product, WbSale

Metric = Literal["revenue", "profit", "qty", "margin"]


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _classify_xyz(cv: float, x_thr: float = 0.10, y_thr: float = 0.25) -> str:
    if cv < x_thr:
        return "X"
    if cv < y_thr:
        return "Y"
    return "Z"


def _classify_abc(
    items_sorted: list[dict[str, Any]],
    total_value: float,
    a_thr: float = 0.80,
    b_thr: float = 0.95,
) -> None:
    """Mutate items in-place, adding `abc_class`, `share_pct`, `cumulative_pct`."""
    cum = 0.0
    for it in items_sorted:
        share = it["value"] / total_value if total_value > 0 else 0.0
        cum += share
        it["share_pct"] = round(share * 100, 2)
        it["cumulative_pct"] = round(cum * 100, 2)
        if cum <= a_thr:
            it["abc_class"] = "A"
        elif cum <= b_thr:
            it["abc_class"] = "B"
        else:
            it["abc_class"] = "C"


async def build_abc_xyz(
    session: AsyncSession,
    *,
    days: int = 90,
    metric: Metric = "revenue",
    include_archived: bool = False,
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Compute ABC+XYZ classification for all SKUs sold in the last `days` days.

    DEV-062: `nm_ids` (глобальные фильтры, RBAC уже учтён) имеет приоритет над
    brand-whitelist.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    if nm_ids is not None:
        nm_filter = select(Product.nm_id).where(Product.nm_id.in_(nm_ids))
    elif brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
    else:
        nm_filter = None

    # Aggregate per SKU: total qty, total revenue, total for_pay (net revenue after WB cut).
    sales_stmt = (
        select(
            WbSale.nm_id,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("qty"),
            func.sum(
                case((WbSale.is_return, 0), else_=WbSale.price_with_disc)
            ).label("revenue"),
            func.sum(
                case((WbSale.is_return, 0), else_=WbSale.for_pay)
            ).label("for_pay"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_rows = (await session.execute(sales_stmt)).all()

    # COGS — latest entry per SKU; for ABC by margin/profit it's a coarse approximation.
    cogs_stmt = select(
        Cogs.nm_id,
        Cogs.cost_rub,
        Cogs.packaging_rub,
        Cogs.fulfillment_rub,
        Cogs.valid_from,
    ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
    if nm_filter is not None:
        cogs_stmt = cogs_stmt.where(Cogs.nm_id.in_(nm_filter))
    cogs_rows = (await session.execute(cogs_stmt)).all()
    cogs_by_nm: dict[int, float] = {}
    for r in cogs_rows:
        nm = int(r.nm_id)
        if nm in cogs_by_nm:
            continue
        cogs_by_nm[nm] = _f(r.cost_rub) + _f(r.packaging_rub) + _f(r.fulfillment_rub)

    # Daily series for XYZ — net qty per day per nm (negative = return-day).
    daily_stmt = (
        select(
            func.date(WbSale.sale_dt).label("d"),
            WbSale.nm_id,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("qty"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by("d", WbSale.nm_id)
    )
    if nm_filter is not None:
        daily_stmt = daily_stmt.where(WbSale.nm_id.in_(nm_filter))
    daily_rows = (await session.execute(daily_stmt)).all()
    series_by_nm: dict[int, dict[date, float]] = defaultdict(dict)
    for r in daily_rows:
        d = r.d if isinstance(r.d, date) else date.fromisoformat(str(r.d))
        series_by_nm[int(r.nm_id)][d] = float(r.qty or 0)

    products_stmt = select(Product)
    if nm_ids is not None:
        products_stmt = products_stmt.where(Product.nm_id.in_(nm_ids))
    elif brands is not None:
        products_stmt = products_stmt.where(Product.brand.in_(list(brands)))
    all_products = (await session.execute(products_stmt)).scalars().all()
    products = {p.nm_id: p for p in all_products}
    archived_nm_ids: set[int] = (
        set() if include_archived else {p.nm_id for p in all_products if p.is_archived}
    )

    # Build per-SKU records
    items: list[dict[str, Any]] = []
    for r in sales_rows:
        nm = int(r.nm_id)
        if nm in archived_nm_ids:
            continue
        qty = int(r.qty or 0)
        revenue = _f(r.revenue)
        for_pay = _f(r.for_pay)
        unit_cost = cogs_by_nm.get(nm, 0.0)
        cogs_total = qty * unit_cost
        profit = for_pay - cogs_total

        if metric == "revenue":
            value = revenue
        elif metric == "qty":
            value = float(qty)
        elif metric == "profit":
            value = profit
        elif metric == "margin":
            value = profit  # margin = profit; "share_pct" tells you the proportion
        else:
            value = revenue

        # XYZ — CV of daily qty series, padded with zeros for missing days.
        series = series_by_nm.get(nm, {})
        cursor = start.date()
        end_d = end.date()
        full_series: list[float] = []
        while cursor < end_d:
            full_series.append(series.get(cursor, 0.0))
            cursor += timedelta(days=1)
        if len(full_series) >= 2 and sum(full_series) > 0:
            mean = statistics.mean(full_series)
            stdev = statistics.pstdev(full_series)
            cv = stdev / mean if mean > 0 else 1.0
        else:
            mean = 0.0
            cv = 1.0  # unsold or tiny tail — Z by default
        xyz = _classify_xyz(cv)

        prod = products.get(nm)
        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": prod.brand if prod else None,
                "qty": qty,
                "revenue": round(revenue, 2),
                "for_pay": round(for_pay, 2),
                "profit": round(profit, 2),
                "unit_cost": round(unit_cost, 2),
                "value": value,            # the metric used for ABC
                "mean_per_day": round(mean, 3),
                "cv": round(cv, 3),
                "xyz_class": xyz,
            }
        )

    # ABC — sort by `value` descending; only positive values participate in ABC.
    items.sort(key=lambda x: x["value"], reverse=True)
    pos = [it for it in items if it["value"] > 0]
    total_value = sum(it["value"] for it in pos)
    _classify_abc(pos, total_value)
    # SKUs with zero / negative value go straight to C with 0 share
    for it in items:
        if it not in pos:
            it["abc_class"] = "C"
            it["share_pct"] = 0.0
            it["cumulative_pct"] = 100.0
        # Combo class
        it["combo_class"] = f"{it['abc_class']}{it['xyz_class']}"

    # Aggregates
    by_class: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "value": 0.0, "share_pct": 0.0}
    )
    for it in items:
        by_class[it["abc_class"]]["count"] += 1
        by_class[it["abc_class"]]["value"] += it["value"]
    for k, v in by_class.items():
        v["value"] = round(v["value"], 2)
        v["share_pct"] = round(v["value"] / total_value * 100, 2) if total_value > 0 else 0.0

    matrix: dict[str, int] = defaultdict(int)
    for it in items:
        matrix[it["combo_class"]] += 1

    return {
        "metric": metric,
        "days": days,
        "total_value": round(total_value, 2),
        "abc_summary": dict(by_class),
        "matrix": dict(matrix),
        "items": items,
    }
