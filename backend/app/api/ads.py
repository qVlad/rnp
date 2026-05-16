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
from app.services.auth import get_db_tenant_scoped

router = APIRouter(prefix="/api/ads", tags=["ads"])


@router.get("/heatmap")
async def get_ads_heatmap(
    start_date: Annotated[date | None, Query(alias="from")] = None,
    end_date: Annotated[date | None, Query(alias="to")] = None,
    days_back: Annotated[int, Query(ge=1, le=180)] = 30,
    metric: Annotated[str, Query(regex="^(drr|spent|orders|clicks|revenue)$")] = "drr",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Heatmap: строки = кампании, колонки = дни, значение = выбранная метрика.

    Параметры:
        metric: 'drr' (default, %), 'spent' (₽), 'orders' (шт), 'clicks' (шт), 'revenue' (₽)
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=days_back)

    # Aggregate per (advert_id, stat_date)
    stmt = (
        select(
            WbAdStatsDaily.advert_id,
            WbAdStatsDaily.stat_date,
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
            func.sum(WbAdStatsDaily.sum_price).label("revenue"),
            func.sum(WbAdStatsDaily.orders).label("orders"),
            func.sum(WbAdStatsDaily.clicks).label("clicks"),
        )
        .where(WbAdStatsDaily.stat_date >= start_date)
        .where(WbAdStatsDaily.stat_date <= end_date)
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
        else:
            val = None
        cell_matrix = matrix.setdefault(r.advert_id, {})
        cell_matrix[r.stat_date.isoformat()] = val
        t = totals_per_camp.setdefault(
            r.advert_id, {"spent": 0.0, "revenue": 0.0, "orders": 0, "clicks": 0}
        )
        t["spent"] += spent
        t["revenue"] += rev
        t["orders"] += orders
        t["clicks"] += clicks

    # Список кампаний — сортируем по общим тратам убывая
    campaigns_out: list[dict[str, Any]] = []
    for adv_id, totals in totals_per_camp.items():
        meta = camp_meta.get(adv_id, {"name": f"#{adv_id}", "status": None})
        drr_total = (
            (totals["spent"] / totals["revenue"] * 100.0)
            if totals["revenue"] > 0
            else None
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
                "drr_total": round(drr_total, 2) if drr_total is not None else None,
                "cells": [matrix.get(adv_id, {}).get(day) for day in days],
            }
        )
    campaigns_out.sort(key=lambda x: x["spent"], reverse=True)

    return {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "metric": metric,
        "days": days,
        "campaigns": campaigns_out,
        "totals": (
            lambda spent_sum, rev_sum: {
                "spent": round(spent_sum, 2),
                "revenue": round(rev_sum, 2),
                "orders": sum(c["orders"] for c in campaigns_out),
                "clicks": sum(c["clicks"] for c in campaigns_out),
                "drr": round(spent_sum / rev_sum * 100, 2) if rev_sum > 0 else None,
            }
        )(
            sum(c["spent"] for c in campaigns_out),
            sum(c["revenue"] for c in campaigns_out),
        ),
    }
