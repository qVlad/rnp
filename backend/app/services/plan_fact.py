"""Compute Plan vs Fact for a given month.

Joins SalesPlan rows with actuals for the same period:
  - orders_qty / orders_revenue   ← from wb_orders (excluding cancellations)
  - sales_qty / sales_revenue     ← from wb_sales  (net of returns)
  - profit                        ← from pnl_builder for the month
  - marketing_cost                ← wb_ad_stats_daily + external_ad_costs

For each plan returns: plan, fact, delta = fact-plan, completion_pct = fact/plan.
"""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ExternalAdCost,
    Product,
    ProductGroup,
    ProductGroupAssignment,
    SalesPlan,
    WbAdStatsDaily,
    WbOrder,
    WbSale,
)
from app.services.pnl_builder import build_pnl
from app.services.unit_economics import build_unit_economics


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _delta(plan: float, fact: float) -> dict[str, float | None]:
    delta = fact - plan
    pct = (fact / plan * 100) if plan > 0 else None
    return {
        "plan": round(plan, 2),
        "fact": round(fact, 2),
        "delta": round(delta, 2),
        "completion_pct": round(pct, 2) if pct is not None else None,
    }


async def build_plan_fact(
    session: AsyncSession,
    *,
    year: int,
    month: int,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Plan vs Fact for one month.

    `brands` filter (manager scope):
        * Drops store-scope plans (they are company-wide).
        * Keeps nm-scope plans whose nm_id belongs to a whitelisted brand.
        * Keeps group-scope plans if at least one assigned nm_id is in scope.
        * All fact aggregates (orders / sales / WB ads / external ads / P&L)
          are restricted to whitelisted nm_ids.
    """
    # Period bounds
    days_in_month = monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end = date(year, month, days_in_month)
    dt_from = datetime.combine(period_start, datetime.min.time())
    dt_to = datetime.combine(period_end + timedelta(days=1), datetime.min.time())

    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    # ── Plans for this month ──
    plan_stmt = select(SalesPlan).where(
        SalesPlan.period_year == year,
        SalesPlan.period_month == month,
    )
    plans = (await session.execute(plan_stmt)).scalars().all()
    if brands is not None:
        # Resolve which group scope_ids touch the whitelisted brands at least once.
        group_ids_in_scope: set[int] = set()
        if any(p.scope_type == "group" for p in plans):
            rows = (
                await session.execute(
                    select(ProductGroupAssignment.group_id)
                    .distinct()
                    .where(ProductGroupAssignment.nm_id.in_(nm_filter))
                )
            ).scalars().all()
            group_ids_in_scope = {int(g) for g in rows}
        nm_ids_in_scope = {
            int(x)
            for x in (await session.execute(nm_filter)).scalars().all()
        }

        def _plan_visible(p: SalesPlan) -> bool:
            if p.scope_type == "store":
                return False
            if p.scope_type == "nm":
                return p.scope_id is not None and int(p.scope_id) in nm_ids_in_scope
            if p.scope_type == "group":
                return p.scope_id is not None and int(p.scope_id) in group_ids_in_scope
            return False

        plans = [p for p in plans if _plan_visible(p)]

    # ── Aggregate facts globally and per-nm to fill any plan scope ──
    # Orders (excluding cancellations): qty + gross revenue
    orders_total_stmt = select(
        func.coalesce(func.count(WbOrder.srid), 0).label("qty"),
        func.coalesce(
            func.sum(WbOrder.total_price * (1 - WbOrder.discount_percent / 100)), 0
        ).label("revenue"),
    ).where(
        WbOrder.order_dt >= dt_from,
        WbOrder.order_dt < dt_to,
        WbOrder.is_cancel.is_(False),
    )
    if nm_filter is not None:
        orders_total_stmt = orders_total_stmt.where(WbOrder.nm_id.in_(nm_filter))
    orders_total = (await session.execute(orders_total_stmt)).one()

    orders_per_nm_stmt = (
        select(
            WbOrder.nm_id,
            func.count(WbOrder.srid).label("qty"),
            func.coalesce(
                func.sum(WbOrder.total_price * (1 - WbOrder.discount_percent / 100)), 0
            ).label("revenue"),
        )
        .where(
            WbOrder.order_dt >= dt_from,
            WbOrder.order_dt < dt_to,
            WbOrder.is_cancel.is_(False),
        )
        .group_by(WbOrder.nm_id)
    )
    if nm_filter is not None:
        orders_per_nm_stmt = orders_per_nm_stmt.where(WbOrder.nm_id.in_(nm_filter))
    orders_per_nm = (await session.execute(orders_per_nm_stmt)).all()
    orders_by_nm: dict[int, dict[str, float]] = {
        int(r.nm_id): {"qty": int(r.qty or 0), "revenue": _f(r.revenue)}
        for r in orders_per_nm
    }

    # Sales (net of returns)
    sales_total_stmt = select(
        func.coalesce(
            func.sum(case((WbSale.is_return, -1), else_=1)), 0
        ).label("qty"),
        func.coalesce(
            func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)), 0
        ).label("revenue"),
    ).where(WbSale.sale_dt >= dt_from, WbSale.sale_dt < dt_to)
    if nm_filter is not None:
        sales_total_stmt = sales_total_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_total = (await session.execute(sales_total_stmt)).one()

    sales_per_nm_stmt = (
        select(
            WbSale.nm_id,
            func.coalesce(
                func.sum(case((WbSale.is_return, -1), else_=1)), 0
            ).label("qty"),
            func.coalesce(
                func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)), 0
            ).label("revenue"),
        )
        .where(WbSale.sale_dt >= dt_from, WbSale.sale_dt < dt_to)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        sales_per_nm_stmt = sales_per_nm_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_per_nm = (await session.execute(sales_per_nm_stmt)).all()
    sales_by_nm: dict[int, dict[str, float]] = {
        int(r.nm_id): {"qty": int(r.qty or 0), "revenue": _f(r.revenue)}
        for r in sales_per_nm
    }

    # Marketing cost: WB ads + external ads (per nm + brand)
    wb_ads_total_stmt = select(
        func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0)
    ).where(
        WbAdStatsDaily.stat_date >= period_start,
        WbAdStatsDaily.stat_date <= period_end,
    )
    if nm_filter is not None:
        wb_ads_total_stmt = wb_ads_total_stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    wb_ads_total = _f((await session.execute(wb_ads_total_stmt)).scalar_one())

    wb_ads_per_nm_stmt = (
        select(
            WbAdStatsDaily.nm_id,
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("cost"),
        )
        .where(
            WbAdStatsDaily.stat_date >= period_start,
            WbAdStatsDaily.stat_date <= period_end,
            WbAdStatsDaily.nm_id.isnot(None),
        )
        .group_by(WbAdStatsDaily.nm_id)
    )
    if nm_filter is not None:
        wb_ads_per_nm_stmt = wb_ads_per_nm_stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    wb_ads_per_nm = (await session.execute(wb_ads_per_nm_stmt)).all()
    wb_ads_by_nm = {int(r.nm_id): _f(r.cost) for r in wb_ads_per_nm}

    ext_ads_total_stmt = select(
        func.coalesce(func.sum(ExternalAdCost.amount), 0)
    ).where(
        ExternalAdCost.spend_date >= period_start,
        ExternalAdCost.spend_date <= period_end,
    )
    if nm_filter is not None:
        # Manager scope: SKU-level (nm_id in scope) + brand-level (brand in
        # manager's brand assignments). Company-wide rows (both NULL) — нет.
        ext_ads_total_stmt = ext_ads_total_stmt.where(
            or_(
                ExternalAdCost.nm_id.in_(nm_filter),
                and_(
                    ExternalAdCost.nm_id.is_(None),
                    ExternalAdCost.brand.in_(brands or []),
                ),
            )
        )
    ext_ads_total = _f((await session.execute(ext_ads_total_stmt)).scalar_one())

    ext_ads_per_nm_stmt = (
        select(
            ExternalAdCost.nm_id,
            func.coalesce(func.sum(ExternalAdCost.amount), 0).label("cost"),
        )
        .where(
            ExternalAdCost.spend_date >= period_start,
            ExternalAdCost.spend_date <= period_end,
            ExternalAdCost.nm_id.isnot(None),
        )
        .group_by(ExternalAdCost.nm_id)
    )
    if nm_filter is not None:
        ext_ads_per_nm_stmt = ext_ads_per_nm_stmt.where(
            ExternalAdCost.nm_id.in_(nm_filter)
        )
    ext_ads_per_nm = (await session.execute(ext_ads_per_nm_stmt)).all()
    ext_ads_by_nm = {int(r.nm_id): _f(r.cost) for r in ext_ads_per_nm}

    # Profit: only at store level (P&L is built per period, not per SKU here).
    pnl = await build_pnl(
        session,
        date_from=period_start,
        date_to=period_end,
        granularity="month",
        brands=brands,
    )
    fact_profit_total = _f(pnl["totals"].get("profit", 0))

    # Per-SKU чистая прибыль для nm- и group-scope строк план-факта.
    # build_unit_economics возвращает items с полем net_profit (revenue −
    # cogs − wb_fees − ad − tax). Используется как агрегируемая единица для
    # group: profit = Σ net_profit по членам группы. OPEX/налоги
    # компании в эту сумму НЕ входят (они per-period, не per-SKU) — поэтому
    # group-profit чуть отличается от full-company profit как контрибуция.
    ue = await build_unit_economics(
        session,
        start_date=period_start,
        end_date=period_end,
        include_archived=True,
        brands=brands,
    )
    profit_by_nm: dict[int, float] = {
        int(it["nm_id"]): _f(it.get("net_profit", 0)) for it in ue.get("items", [])
    }

    # Product names for SKU-level plans
    product_ids = [p.scope_id for p in plans if p.scope_type == "nm" and p.scope_id]
    product_map: dict[int, Product] = {}
    if product_ids:
        rows = (
            await session.execute(
                select(Product).where(Product.nm_id.in_(product_ids))
            )
        ).scalars().all()
        product_map = {p.nm_id: p for p in rows}

    # Group-scope: для каждого group_id из планов собираем список входящих
    # nm_id (через ProductGroupAssignment) + получаем human-readable group.name.
    group_ids = [
        p.scope_id for p in plans if p.scope_type == "group" and p.scope_id
    ]
    group_name_map: dict[int, str] = {}
    group_nms_map: dict[int, set[int]] = {}
    if group_ids:
        # Имена групп
        gname_rows = (
            await session.execute(
                select(ProductGroup.id, ProductGroup.name).where(
                    ProductGroup.id.in_(group_ids)
                )
            )
        ).all()
        group_name_map = {int(r.id): r.name for r in gname_rows}
        # nm_id'ы каждой группы (с учётом brand-фильтра — manager не должен
        # видеть факт по nm_id не своих брендов даже внутри группы).
        ga_stmt = select(
            ProductGroupAssignment.group_id, ProductGroupAssignment.nm_id
        ).where(ProductGroupAssignment.group_id.in_(group_ids))
        if nm_filter is not None:
            ga_stmt = ga_stmt.where(ProductGroupAssignment.nm_id.in_(nm_filter))
        ga_rows = (await session.execute(ga_stmt)).all()
        for r in ga_rows:
            group_nms_map.setdefault(int(r.group_id), set()).add(int(r.nm_id))

    # Build per-plan items
    items: list[dict[str, Any]] = []
    for p in plans:
        if p.scope_type == "store":
            f_orders_qty = int(orders_total.qty or 0)
            f_orders_rev = _f(orders_total.revenue)
            f_sales_qty = int(sales_total.qty or 0)
            f_sales_rev = _f(sales_total.revenue)
            f_marketing = wb_ads_total + ext_ads_total
            f_profit = fact_profit_total
            label = "Магазин (всего)"
        elif p.scope_type == "nm" and p.scope_id is not None:
            nm = int(p.scope_id)
            f_orders_qty = orders_by_nm.get(nm, {}).get("qty", 0)
            f_orders_rev = orders_by_nm.get(nm, {}).get("revenue", 0.0)
            f_sales_qty = sales_by_nm.get(nm, {}).get("qty", 0)
            f_sales_rev = sales_by_nm.get(nm, {}).get("revenue", 0.0)
            f_marketing = wb_ads_by_nm.get(nm, 0.0) + ext_ads_by_nm.get(nm, 0.0)
            # Per-SKU net_profit берётся из build_unit_economics. Если SKU
            # отсутствует в UE (нет ни заказов, ни продаж за период) —
            # показываем 0, не None: «факта нет» = «прибыли нет».
            f_profit = profit_by_nm.get(nm, 0.0)
            prod = product_map.get(nm)
            label = (
                f"SKU {nm}" + (f" — {prod.vendor_code}" if prod and prod.vendor_code else "")
            )
        elif p.scope_type == "group" and p.scope_id is not None:
            gid = int(p.scope_id)
            members = group_nms_map.get(gid, set())
            f_orders_qty = sum(orders_by_nm.get(n, {}).get("qty", 0) for n in members)
            f_orders_rev = sum(
                orders_by_nm.get(n, {}).get("revenue", 0.0) for n in members
            )
            f_sales_qty = sum(sales_by_nm.get(n, {}).get("qty", 0) for n in members)
            f_sales_rev = sum(
                sales_by_nm.get(n, {}).get("revenue", 0.0) for n in members
            )
            f_marketing = sum(
                wb_ads_by_nm.get(n, 0.0) + ext_ads_by_nm.get(n, 0.0) for n in members
            )
            # Per-group net_profit = Σ net_profit членов группы (из UE).
            # Это контрибуционная маржа группы; OPEX/налоги компании
            # сюда не входят (они per-period, не per-SKU), поэтому сумма
            # group-profit по всем группам < company-profit на P&L.
            f_profit = sum(profit_by_nm.get(n, 0.0) for n in members)
            gname = group_name_map.get(gid, f"#{gid}")
            label = f"Группа: {gname}" + (
                f" ({len(members)} SKU)" if members else " (нет SKU)"
            )
        else:
            # store-scope без scope_id уже обработан выше; сюда падает только
            # некорректная комбинация (group без scope_id и т.п.) — заглушка.
            f_orders_qty = 0
            f_orders_rev = 0.0
            f_sales_qty = 0
            f_sales_rev = 0.0
            f_marketing = 0.0
            f_profit = None
            label = f"Неизвестный scope {p.scope_type}/{p.scope_id}"

        items.append(
            {
                "plan_id": p.id,
                "scope_type": p.scope_type,
                "scope_id": p.scope_id,
                "label": label,
                "comment": p.comment,
                "metrics": {
                    "orders_qty": _delta(float(p.planned_orders_qty), float(f_orders_qty)),
                    "orders_revenue": _delta(_f(p.planned_orders_revenue), f_orders_rev),
                    "sales_qty": _delta(float(p.planned_sales_qty), float(f_sales_qty)),
                    "sales_revenue": _delta(_f(p.planned_sales_revenue), f_sales_rev),
                    "marketing_cost": _delta(_f(p.planned_marketing_cost), f_marketing),
                    "profit": (
                        _delta(_f(p.planned_profit), f_profit)
                        if f_profit is not None
                        else {
                            "plan": _f(p.planned_profit),
                            "fact": None,
                            "delta": None,
                            "completion_pct": None,
                        }
                    ),
                },
            }
        )

    return {
        "year": year,
        "month": month,
        "fact_period": {
            "from": period_start.isoformat(),
            "to": period_end.isoformat(),
        },
        "items": items,
    }
