"""Funnel views → cart → order → buyout per-SKU (TASK-LEAD-025).

У MPump «Воронка продаж и Конверсии» — first-class функционал. У нас был
только скаляр `buyout_pct` — узкое место воронки не видно. Здесь — per-nm
waterfall за период с conv-rates между шагами.

Источник:
  - WbAdStatsDaily.views   → показы
  - WbAdStatsDaily.atbs    → добавления в корзину (Add To Basket)
  - WbAdStatsDaily.orders  → заказы из рекламы
  - WbReportDetail (supplier_oper_name='Продажа') → выкупы по nm_id

Только реклама в первых трёх шагах — органика не учитывается в funnel API.
Это сужает scope, но MVP. Расширение — собрать показы из `/v1/analytics`
(WB Statistics) когда лимиты позволят.

Endpoint: `GET /api/funnel/by-sku?days=14`. brands-filter применяется.
Доступ: brands-filter (manager — свои).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbAdStatsDaily, WbReportDetail
from app.services.auth import current_brands_filter, get_db_tenant_scoped
from app.services.period_aggregates import OP_RETURN, OP_SALE


router = APIRouter(prefix="/api/funnel", tags=["funnel"])


@router.get("/by-sku")
async def funnel_by_sku(
    days: int = Query(default=14, ge=1, le=90),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Воронка per-SKU за окно `days` дней.

    Возвращает:
      - items: список {nm_id, vendor_code, subject, brand, views, atbs,
        orders, buyouts, ctr_pct, cart_rate_pct, order_rate_pct,
        buyout_rate_pct, weakest_step}
      - totals: суммы по всему листу + рейты на total-уровне
    """
    today = date.today()
    date_to = today
    date_from = today - timedelta(days=days)

    # 1) Ad-stats aggregate per nm_id за окно
    ad_stmt = (
        select(
            WbAdStatsDaily.nm_id,
            func.sum(WbAdStatsDaily.views).label("views"),
            func.sum(WbAdStatsDaily.atbs).label("atbs"),
            func.sum(WbAdStatsDaily.orders).label("orders"),
        )
        .where(
            WbAdStatsDaily.stat_date >= date_from,
            WbAdStatsDaily.stat_date < date_to,
            WbAdStatsDaily.nm_id.isnot(None),
        )
        .group_by(WbAdStatsDaily.nm_id)
    )
    if brands is not None:
        ad_stmt = ad_stmt.where(
            WbAdStatsDaily.nm_id.in_(
                select(Product.nm_id).where(Product.brand.in_(list(brands)))
            )
        )

    ad_rows = (await session.execute(ad_stmt)).all()
    ad_by_nm: dict[int, dict[str, int]] = {
        int(r.nm_id): {
            "views": int(r.views or 0),
            "atbs": int(r.atbs or 0),
            "orders": int(r.orders or 0),
        }
        for r in ad_rows
    }

    if not ad_by_nm:
        return {
            "days": days,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "items": [],
            "totals": {
                "views": 0, "atbs": 0, "orders": 0, "buyouts": 0,
                "ctr_pct": 0, "cart_rate_pct": 0,
                "order_rate_pct": 0, "buyout_rate_pct": 0,
            },
        }

    # 2) Buyouts per nm_id из WbReportDetail. supplier_oper_name='Продажа' минус 'Возврат'.
    nm_ids = list(ad_by_nm.keys())
    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == OP_SALE, 1),
                    (WbReportDetail.supplier_oper_name == OP_RETURN, -1),
                    else_=0,
                )
            ).label("buyouts"),
        )
        .where(
            WbReportDetail.nm_id.in_(nm_ids),
            WbReportDetail.sale_dt >= date_from,
            WbReportDetail.sale_dt < date_to,
        )
        .group_by(WbReportDetail.nm_id)
    )
    rd_rows = (await session.execute(rd_stmt)).all()
    buyouts_by_nm: dict[int, int] = {
        int(r.nm_id): max(int(r.buyouts or 0), 0) for r in rd_rows
    }

    # 3) Product metadata (vendor_code, subject, brand)
    prod_rows = (
        await session.execute(
            select(Product.nm_id, Product.vendor_code, Product.subject, Product.brand)
            .where(Product.nm_id.in_(nm_ids))
        )
    ).all()
    meta_by_nm = {int(p.nm_id): p for p in prod_rows}

    def _pct(num: int, denom: int) -> float:
        return round(num / denom * 100, 2) if denom > 0 else 0.0

    def _weakest_step(views: int, atbs: int, orders: int, buyouts: int) -> str:
        # Самый низкий conv-rate = "слабое звено" воронки
        ctr = atbs / views if views > 0 else 1.0
        cart = orders / atbs if atbs > 0 else 1.0
        order = buyouts / orders if orders > 0 else 1.0
        worst = min(ctr, cart, order)
        if worst == ctr:
            return "views→cart"
        if worst == cart:
            return "cart→order"
        return "order→buyout"

    items: list[dict[str, Any]] = []
    for nm_id, ad in ad_by_nm.items():
        meta = meta_by_nm.get(nm_id)
        v, a, o = ad["views"], ad["atbs"], ad["orders"]
        b = buyouts_by_nm.get(nm_id, 0)
        items.append(
            {
                "nm_id": nm_id,
                "vendor_code": meta.vendor_code if meta else None,
                "subject": meta.subject if meta else None,
                "brand": meta.brand if meta else None,
                "views": v,
                "atbs": a,
                "orders": o,
                "buyouts": b,
                "ctr_pct": _pct(a, v),
                "cart_rate_pct": _pct(o, a),
                "buyout_rate_pct": _pct(b, o),
                "weakest_step": _weakest_step(v, a, o, b),
            }
        )

    # Sort: по показу но «слабая ступень» — Front может потом сортировать
    items.sort(key=lambda x: -x["views"])

    # Totals
    tv = sum(it["views"] for it in items)
    ta = sum(it["atbs"] for it in items)
    to = sum(it["orders"] for it in items)
    tb = sum(it["buyouts"] for it in items)
    totals = {
        "views": tv,
        "atbs": ta,
        "orders": to,
        "buyouts": tb,
        "ctr_pct": _pct(ta, tv),
        "cart_rate_pct": _pct(to, ta),
        "buyout_rate_pct": _pct(tb, to),
        "overall_conv_pct": _pct(tb, tv),
    }

    return {
        "days": days,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "items": items,
        "totals": totals,
    }
