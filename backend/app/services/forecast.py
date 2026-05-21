"""Stockout forecast and supply recommendation.

Two pieces of information per SKU:
  1. days_to_zero    — current_stock / velocity_per_day (how soon you'll run out)
  2. recommended_qty — qty needed to cover next N days at current velocity

Velocity is the average daily net qty (sales − returns) over a configurable
rolling window (default 14 days). Stock is the latest snapshot from
wb_stocks_snapshot, summed across all warehouses.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, Product, User, WbSale, WbStockSnapshot
from app.services.cogs_weighted import compute_weighted_avg_cogs


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _classify_urgency(days_to_zero: float | None, warning_days: float = 7) -> str:
    if days_to_zero is None:
        return "no_sales"
    if days_to_zero <= warning_days:
        return "critical"
    if days_to_zero <= warning_days * 2:
        return "warning"
    return "ok"


async def build_stockout_forecast(
    session: AsyncSession,
    *,
    velocity_window: int = 14,
    target_days: int = 30,
    warning_days: float = 7,
    include_archived: bool = False,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Return per-SKU stockout forecast with recommended supply.

    Args:
        velocity_window: rolling window in days for computing avg daily sales
        target_days:     supply horizon — how many days the recommendation should cover
        warning_days:    threshold for "critical" urgency classification
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=velocity_window)
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    # Velocity per SKU: net qty / window
    vel_stmt = (
        select(
            WbSale.nm_id,
            func.coalesce(
                func.sum(case((WbSale.is_return, -1), else_=1)), 0
            ).label("net_qty"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        vel_stmt = vel_stmt.where(WbSale.nm_id.in_(nm_filter))
    vel_rows = (await session.execute(vel_stmt)).all()
    velocity_by_nm: dict[int, float] = {
        int(r.nm_id): float(r.net_qty or 0) / max(velocity_window, 1) for r in vel_rows
    }

    # Latest stock snapshot
    latest_dt = select(func.max(WbStockSnapshot.snapshot_dt)).scalar_subquery()
    stock_stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
            func.coalesce(func.sum(WbStockSnapshot.quantity), 0).label("avail"),
            func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("in_to"),
            func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("in_from"),
        )
        .where(WbStockSnapshot.snapshot_dt == latest_dt)
        .group_by(WbStockSnapshot.nm_id)
    )
    if nm_filter is not None:
        stock_stmt = stock_stmt.where(WbStockSnapshot.nm_id.in_(nm_filter))
    stock_rows = (await session.execute(stock_stmt)).all()
    stock_by_nm: dict[int, dict[str, int]] = {
        int(r.nm_id): {
            "quantity_full": int(r.qty or 0),
            "available": int(r.avail or 0),
            "in_way_to_client": int(r.in_to or 0),
            "in_way_from_client": int(r.in_from or 0),
        }
        for r in stock_rows
    }

    products_stmt = select(Product)
    if brands is not None:
        products_stmt = products_stmt.where(Product.brand.in_(list(brands)))
    all_products = (await session.execute(products_stmt)).scalars().all()
    products = {p.nm_id: p for p in all_products}
    archived_nm_ids: set[int] = (
        set() if include_archived else {p.nm_id for p in all_products if p.is_archived}
    )

    nm_set = set(velocity_by_nm.keys()) | set(stock_by_nm.keys())

    # TASK-DEV-021: COGS per unit (weighted avg) — для CSV-выгрузки в 1С.
    # Берём supplies на дату генерации прогноза. paid_only=False — для
    # планирования закупок учитываем и неоплаченные поставки, иначе COGS
    # окажется заниженной если последняя крупная закупка ещё не оплачена.
    cogs_by_nm: dict[int, dict[str, float]] = {}
    if nm_set:
        cogs_by_nm = await compute_weighted_avg_cogs(
            session,
            nm_ids=nm_set,
            period_end=date.today(),
            paid_only=False,
        )

    # TASK-DEV-021: manager_name per brand. Если у бренда ровно 1 manager —
    # подставляем его ФИО (для согласования заявки РОПом). Если 0 или ≥2 —
    # пусто (РОП доберёт контакт сам).
    ba_stmt = (
        select(BrandAssignment.brand, User.full_name, User.username)
        .join(User, User.id == BrandAssignment.user_id)
        .where(User.is_active.is_(True))
    )
    if brands is not None:
        ba_stmt = ba_stmt.where(BrandAssignment.brand.in_(list(brands)))
    ba_rows = (await session.execute(ba_stmt)).all()
    managers_by_brand_raw: dict[str, list[str]] = {}
    for r in ba_rows:
        name = (r.full_name or r.username or "").strip()
        if not name:
            continue
        managers_by_brand_raw.setdefault(r.brand, []).append(name)
    manager_by_brand: dict[str, str | None] = {
        b: (names[0] if len(names) == 1 else None)
        for b, names in managers_by_brand_raw.items()
    }

    if archived_nm_ids:
        nm_set -= archived_nm_ids
    items: list[dict[str, Any]] = []
    for nm in nm_set:
        velocity = velocity_by_nm.get(nm, 0.0)
        stock_info = stock_by_nm.get(nm, {})
        stock = stock_info.get("quantity_full", 0)
        prod = products.get(nm)

        if velocity > 0:
            days_to_zero = stock / velocity
            target_qty = velocity * target_days
            recommended = max(0, int(round(target_qty - stock)))
        else:
            days_to_zero = None
            recommended = 0

        urgency = _classify_urgency(days_to_zero, warning_days)

        cogs_per_unit = cogs_by_nm.get(nm, {}).get("avg_cost")
        cogs_total = (
            round(cogs_per_unit * recommended, 2)
            if cogs_per_unit is not None and recommended > 0
            else None
        )
        brand_name = prod.brand if prod else None
        manager_name = manager_by_brand.get(brand_name) if brand_name else None

        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": brand_name,
                "stock": stock,
                "available": stock_info.get("available", 0),
                "in_way_to_client": stock_info.get("in_way_to_client", 0),
                "in_way_from_client": stock_info.get("in_way_from_client", 0),
                "velocity_per_day": round(velocity, 3),
                "days_to_zero": round(days_to_zero, 1) if days_to_zero is not None else None,
                "recommended_supply_qty": recommended,
                "urgency": urgency,
                # TASK-DEV-021: для CSV-выгрузки в 1С / согласования с РОПом
                "cogs_per_unit": round(cogs_per_unit, 2) if cogs_per_unit is not None else None,
                "cogs_total": cogs_total,
                "manager_name": manager_name,
            }
        )

    # Sort: critical first by days_to_zero ascending, then warnings, then ok, then no_sales
    URGENCY_ORDER = {"critical": 0, "warning": 1, "ok": 2, "no_sales": 3}
    items.sort(
        key=lambda it: (
            URGENCY_ORDER.get(it["urgency"], 9),
            it["days_to_zero"] if it["days_to_zero"] is not None else 1e9,
            -it["velocity_per_day"],
        )
    )

    summary = {
        "critical": sum(1 for it in items if it["urgency"] == "critical"),
        "warning": sum(1 for it in items if it["urgency"] == "warning"),
        "ok": sum(1 for it in items if it["urgency"] == "ok"),
        "no_sales": sum(1 for it in items if it["urgency"] == "no_sales"),
        "total_recommended_qty": sum(it["recommended_supply_qty"] for it in items),
    }

    return {
        "velocity_window": velocity_window,
        "target_days": target_days,
        "warning_days": warning_days,
        "summary": summary,
        "items": items,
    }
