"""Рекламная аналитика — heatmap (день × кампания) + сводка по кампаниям.

Источник: `wb_ad_stats_daily` (синк через `/adv/v3/fullstats`). Метрика
для тепловой карты — ДРР (доля рекламных расходов) = `sum_spent / sum_price × 100`,
если sum_price > 0, иначе null (без данных).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbAdCampaign, WbAdStatsDaily
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.tenant_context import set_tenant_filter

router = APIRouter(prefix="/api/ads", tags=["ads"])


@router.get("/heatmap")
async def get_ads_heatmap(
    start_date: Annotated[date | None, Query(alias="from")] = None,
    end_date: Annotated[date | None, Query(alias="to")] = None,
    days_back: Annotated[int, Query(ge=1, le=180)] = 30,
    metric: Annotated[
        str,
        Query(
            regex="^(drr|spent|orders|clicks|revenue|cpl|cps|basket_conv|order_conv)$"
        ),
    ] = "drr",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Heatmap: строки = кампании, колонки = дни, значение = выбранная метрика.

    Параметры:
        metric: 'drr' (default, %), 'spent' (₽), 'orders' (шт), 'clicks' (шт),
                'revenue' (₽), 'cpl' (₽/клик), 'cps' (₽/заказ),
                'basket_conv' (%, atbs/clicks), 'order_conv' (%, orders/clicks)

    Conversion-метрики (TASK-LEAD-033) считаются sum-numerator/sum-denominator
    (НЕ среднее средних — match с funnel logic):
        cpl         = spent / clicks               (null если clicks=0)
        cps         = spent / orders               (null если orders=0)
        basket_conv = atbs / clicks × 100          (null если clicks=0)
        order_conv  = orders / clicks × 100        (null если clicks=0)
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=days_back)

    # DEV-062 Phase C: свод по магазинам (≥2 кабинета) → расширить ORM-фильтр.
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=brands,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    # DEV-062: глобальные фильтры → nm_id-предикат (РК атрибутируются к карточке).
    # BUG-DEV-024: RBAC применяется ВСЕГДА для brand-scoped роли (manager), даже
    # без выбранного фильтра — иначе manager видел бы все кампании тенанта.
    nm_pred = []
    if any([glob_brands, categories, groups, articles]) or brands is not None:
        nm_scope = await resolve_nm_scope(
            session, brands=glob_brands, categories=categories, groups=groups,
            articles=articles, rbac_brands=brands,
        )
        if nm_scope is not None:
            nm_pred = [WbAdStatsDaily.nm_id.in_(nm_scope)]

    # Aggregate per (advert_id, stat_date)
    stmt = (
        select(
            WbAdStatsDaily.advert_id,
            WbAdStatsDaily.stat_date,
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
            func.sum(WbAdStatsDaily.sum_price).label("revenue"),
            func.sum(WbAdStatsDaily.orders).label("orders"),
            func.sum(WbAdStatsDaily.clicks).label("clicks"),
            func.sum(WbAdStatsDaily.atbs).label("atbs"),
        )
        .where(WbAdStatsDaily.stat_date >= start_date)
        .where(WbAdStatsDaily.stat_date <= end_date)
        .where(*nm_pred)
        .group_by(WbAdStatsDaily.advert_id, WbAdStatsDaily.stat_date)
    )
    rows = (await session.execute(stmt)).all()

    # Имена кампаний из wb_ad_campaigns
    campaigns_stmt = select(WbAdCampaign.advert_id, WbAdCampaign.name, WbAdCampaign.status)
    campaigns_rows = (await session.execute(campaigns_stmt)).all()
    camp_meta = {c.advert_id: {"name": c.name or f"#{c.advert_id}", "status": c.status} for c in campaigns_rows}

    # Группируем в матрицу: campaigns × days
    days: list[str] = []
    d = start_date
    while d <= end_date:
        days.append(d.isoformat())
        d += timedelta(days=1)

    # campaign_id → {day_iso → metric_value}
    matrix: dict[int, dict[str, float | None]] = {}
    totals_per_camp: dict[int, dict[str, float]] = {}
    for r in rows:
        spent = float(r.spent or 0)
        rev = float(r.revenue or 0)
        orders = int(r.orders or 0)
        clicks = int(r.clicks or 0)
        atbs = int(r.atbs or 0)
        if metric == "drr":
            val: float | None = (spent / rev * 100.0) if rev > 0 else None
        elif metric == "spent":
            val = spent
        elif metric == "revenue":
            val = rev
        elif metric == "orders":
            val = float(orders)
        elif metric == "clicks":
            val = float(clicks)
        elif metric == "cpl":
            val = (spent / clicks) if clicks > 0 else None
        elif metric == "cps":
            val = (spent / orders) if orders > 0 else None
        elif metric == "basket_conv":
            val = (atbs / clicks * 100.0) if clicks > 0 else None
        elif metric == "order_conv":
            val = (orders / clicks * 100.0) if clicks > 0 else None
        else:
            val = None
        cell_matrix = matrix.setdefault(r.advert_id, {})
        cell_matrix[r.stat_date.isoformat()] = val
        t = totals_per_camp.setdefault(
            r.advert_id,
            {"spent": 0.0, "revenue": 0.0, "orders": 0, "clicks": 0, "atbs": 0},
        )
        t["spent"] += spent
        t["revenue"] += rev
        t["orders"] += orders
        t["clicks"] += clicks
        t["atbs"] += atbs

    # Список кампаний — сортируем по общим тратам убывая
    campaigns_out: list[dict[str, Any]] = []
    for adv_id, totals in totals_per_camp.items():
        meta = camp_meta.get(adv_id, {"name": f"#{adv_id}", "status": None})
        drr_total = (
            (totals["spent"] / totals["revenue"] * 100.0)
            if totals["revenue"] > 0
            else None
        )
        cpl_total = (totals["spent"] / totals["clicks"]) if totals["clicks"] > 0 else None
        cps_total = (totals["spent"] / totals["orders"]) if totals["orders"] > 0 else None
        basket_conv_total = (
            (totals["atbs"] / totals["clicks"] * 100.0) if totals["clicks"] > 0 else None
        )
        order_conv_total = (
            (totals["orders"] / totals["clicks"] * 100.0) if totals["clicks"] > 0 else None
        )
        campaigns_out.append(
            {
                "advert_id": adv_id,
                "name": meta["name"],
                "status": meta["status"],
                "spent": round(totals["spent"], 2),
                "revenue": round(totals["revenue"], 2),
                "orders": int(totals["orders"]),
                "clicks": int(totals["clicks"]),
                "atbs": int(totals["atbs"]),
                "drr_total": round(drr_total, 2) if drr_total is not None else None,
                "cpl_total": round(cpl_total, 2) if cpl_total is not None else None,
                "cps_total": round(cps_total, 2) if cps_total is not None else None,
                "basket_conv_total": (
                    round(basket_conv_total, 1) if basket_conv_total is not None else None
                ),
                "order_conv_total": (
                    round(order_conv_total, 1) if order_conv_total is not None else None
                ),
                "cells": [matrix.get(adv_id, {}).get(day) for day in days],
            }
        )
    campaigns_out.sort(key=lambda x: x["spent"], reverse=True)

    spent_sum = sum(c["spent"] for c in campaigns_out)
    rev_sum = sum(c["revenue"] for c in campaigns_out)
    orders_sum = sum(c["orders"] for c in campaigns_out)
    clicks_sum = sum(c["clicks"] for c in campaigns_out)
    atbs_sum = sum(c["atbs"] for c in campaigns_out)

    return {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "metric": metric,
        "days": days,
        "campaigns": campaigns_out,
        "totals": {
            "spent": round(spent_sum, 2),
            "revenue": round(rev_sum, 2),
            "orders": orders_sum,
            "clicks": clicks_sum,
            "atbs": atbs_sum,
            "drr": round(spent_sum / rev_sum * 100, 2) if rev_sum > 0 else None,
            "cpl": round(spent_sum / clicks_sum, 2) if clicks_sum > 0 else None,
            "cps": round(spent_sum / orders_sum, 2) if orders_sum > 0 else None,
            "basket_conv": (
                round(atbs_sum / clicks_sum * 100, 1) if clicks_sum > 0 else None
            ),
            "order_conv": (
                round(orders_sum / clicks_sum * 100, 1) if clicks_sum > 0 else None
            ),
        },
        # Tooltip-формулы (TASK-LEAD-033) — фронт может использовать вместо
        # хардкода. Ключи совпадают с именами метрик.
        "metric_formulas": {
            "drr": "spent / revenue × 100",
            "spent": "Σ sum_spent",
            "revenue": "Σ sum_price",
            "orders": "Σ orders",
            "clicks": "Σ clicks",
            "cpl": "spent / clicks",
            "cps": "spent / orders",
            "basket_conv": "atbs / clicks × 100",
            "order_conv": "orders / clicks × 100",
        },
    }
