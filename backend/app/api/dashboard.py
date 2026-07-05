import hashlib
import json
from datetime import date, timedelta
from typing import Annotated, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import AlertAcknowledgement
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    current_tenant_id,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.anomaly import collect_alerts
from app.services.kpi_breakdown import (
    METRIC_LABELS,
    BreakdownMetric,
    compute_kpi_breakdown,
)
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.tenant_context import set_tenant_filter
from app.services.metrics import compute_dashboard, revenue_timeseries, top_skus
from app.services.periods import Period, get_period, period_from_range
from app.services.weekly_changes import build_weekly_changes

log = get_logger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def _resolve_global_filter(
    session: AsyncSession,
    *,
    glob_brands: str | None,
    categories: str | None,
    groups: str | None,
    articles: str | None,
    rbac_brands: set[str] | None,
) -> set[int] | None:
    """DEV-062: свести панель глобальных фильтров к набору nm_id (RBAC учтён).

    None ⇒ панель фильтров пуста → callee применяет brand-scope (RBAC) как раньше.
    Любой непустой выбор → set[int] (RBAC уже пересечён, возможно пустой = пусто).
    """
    if not any([glob_brands, categories, groups, articles]):
        return None  # фильтр не задан — оставляем legacy brand-scope (RBAC)
    return await resolve_nm_scope(
        session, brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=rbac_brands,
    )


async def _apply_store_filter(
    session: AsyncSession, *, stores: str | None, user: CurrentUser,
    rbac_brands: set[str] | None,
) -> list[int] | None:
    """DEV-062 Phase C / DEV-092: свод по кабинетам. Без выбранных магазинов
    у director/head с ≥2 видимыми кабинетами — свод по ВСЕМ (default, как
    TrueStats). Расширяет ORM-фильтр (`tenant_id IN`) и возвращает список
    tenant'ов свода (None = обычный single-tenant).
    BUG-DEV-023: для brand-scoped роли (manager) свод запрещён (RBAC по
    brand-name утёк бы кросс-tenant) — `rbac_brands` прокидываем в резолвер."""
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id,
        rbac_brands=rbac_brands,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
        return store_ids
    return None


def _resolve_period(
    period: str,
    start_date: date | None,
    end_date: date | None,
) -> Period:
    """Either both date bounds are supplied (custom range) or use the named preset."""
    if start_date and end_date:
        try:
            return period_from_range(start_date, end_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if start_date or end_date:
        raise HTTPException(
            status_code=400, detail="start_date and end_date must be supplied together"
        )
    if period not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail=f"unknown period: {period}")
    return get_period(period)  # type: ignore[arg-type]


@router.get("")
async def get_dashboard(
    period: Literal["day", "week", "month"] = "day",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    store_ids = await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    out = await compute_dashboard(
        session,
        _resolve_period(period, start_date, end_date),
        brands=None if nm_ids is not None else brands,
        nm_ids=nm_ids,
        mode=mode,
        reporting_mode=reporting_mode,
        multi_store=bool(store_ids),
        store_ids=store_ids,
    )
    if store_ids:
        out["consolidated"] = len(store_ids)  # DEV-092: бейдж «Свод: N кабинетов»
    return out


@router.get("/extended-kpis")
async def get_extended_kpis(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Literal["operational", "financial"] = "financial",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    include_prev: Annotated[bool, Query()] = True,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """DEV-094 (TS-паритет, 37 плиток): расширенные KPI из движка сводного
    отчёта — вознаграждение ВБ, факт/номинальная комиссия, эквайринг,
    налоговая база, капитализации ×3, остатки ×4, GMROI ×2, оборачиваемость ×2,
    средние ×4, ДРР бонусов/общая, приёмка, компенсации, штрафы.

    Только director/head (движок summary_report — не brand-scoped);
    manager получает 403 через RBAC ниже.
    """
    if brands is not None:
        raise HTTPException(403, "extended-kpis доступен director/head")
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id,
        rbac_brands=brands,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(
        session, brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    from app.services.summary_metrics import build_summary_report  # noqa: WPS433

    data = await build_summary_report(
        session, start_date=start_date, end_date=end_date,
        reporting_mode=reporting_mode, nm_scope=nm_scope,
        include_prev=include_prev,
    )
    return {
        "totals": data["totals"],
        "prev_totals": data.get("prev_totals"),
        "prev_period": data.get("prev_period"),
        "logistics_breakdown": data["logistics_breakdown"],
        "fines_breakdown": data["fines_breakdown"],
        "compensation_breakdown": data["compensation_breakdown"],
        "published_through": data["published_through"],
        "estimated_from": data["estimated_from"],
        "consolidated": len(store_ids) if store_ids else None,
    }


@router.get("/period-chart")
async def get_period_chart(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    compare: Annotated[bool, Query()] = False,
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """«Период в графике» (TASK-DEV-097, как TS): дневные серии 8 метрик —
    Продажи ₽ / Ср. цена до скидок МП / Заказы ₽ / ДРРп % / Логистика /
    Возвраты ₽ / Чистая прибыль / Хранение. `compare=true` добавляет те же
    серии за предыдущий период той же длины (prev выровнен по индексу дня).

    Источники: wb_report_detail (period_aggregates-предикаты), wb_orders,
    wb_ad_stats_daily, build_pnl(day) — только для строки прибыли.
    Director/head (чистая прибыль — company-scope).
    """
    if brands is not None:
        raise HTTPException(403, "period-chart доступен director/head")
    await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )

    from sqlalchemy import case, func

    from app.db.models import WbAdStatsDaily, WbOrder, WbReportDetail
    from app.services.period_aggregates import (
        OP_RETURN,
        OP_SALE,
        REVENUE_FIELD,
        get_period_day,
        get_period_filter,
    )
    from app.services.pnl_builder import build_pnl

    nm_pred_rd = [WbReportDetail.nm_id.in_(nm_ids)] if nm_ids is not None else []

    async def day_series(d_from: date, d_to: date) -> list[dict]:
        day_col = get_period_day(reporting_mode)
        rd = (
            await session.execute(
                select(
                    day_col.label("d"),
                    func.coalesce(func.sum(case((OP_SALE, REVENUE_FIELD), else_=0))
                                  - func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0)), 0).label("sales"),
                    func.coalesce(func.sum(case((OP_SALE, WbReportDetail.retail_price), else_=0)), 0).label("realisation"),
                    func.coalesce(func.sum(case((OP_SALE, WbReportDetail.quantity), else_=0)), 0).label("qty"),
                    func.coalesce(func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0)), 0).label("returns_rub"),
                    func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("logistics"),
                    func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
                )
                .where(*get_period_filter(d_from, d_to, reporting_mode), *nm_pred_rd)
                .group_by(day_col)
            )
        ).all()
        rd_by_day = {r.d.isoformat(): r for r in rd if r.d}

        orows = (
            await session.execute(
                select(
                    func.date(WbOrder.order_dt).label("d"),
                    func.coalesce(func.sum(func.coalesce(WbOrder.price_with_disc, WbOrder.total_price)), 0).label("amt"),
                )
                .where(
                    func.date(WbOrder.order_dt) >= d_from,
                    func.date(WbOrder.order_dt) <= d_to,
                    WbOrder.is_cancel.is_(False),
                    *([WbOrder.nm_id.in_(nm_ids)] if nm_ids is not None else []),
                )
                .group_by(func.date(WbOrder.order_dt))
            )
        ).all()
        orders_by_day = {r.d.isoformat(): float(r.amt or 0) for r in orows}

        arows = (
            await session.execute(
                select(
                    WbAdStatsDaily.stat_date.label("d"),
                    func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
                )
                .where(
                    WbAdStatsDaily.stat_date >= d_from,
                    WbAdStatsDaily.stat_date <= d_to,
                    *([WbAdStatsDaily.nm_id.in_(nm_ids)] if nm_ids is not None else []),
                )
                .group_by(WbAdStatsDaily.stat_date)
            )
        ).all()
        ad_by_day = {r.d.isoformat(): float(r.spent or 0) for r in arows}

        pnl = await build_pnl(
            session, date_from=d_from, date_to=d_to, granularity="day",
            brands=None, nm_ids=nm_ids, reporting_mode=reporting_mode,
        )
        profit_by_day = {r["period_start"]: r.get("profit") for r in pnl["rows"]}

        out = []
        cur = d_from
        while cur <= d_to:
            k = cur.isoformat()
            r = rd_by_day.get(k)
            sales = float(r.sales) if r else 0.0
            qty = int(r.qty) if r else 0
            spent = ad_by_day.get(k, 0.0)
            out.append({
                "date": k,
                "sales": round(sales, 2),
                "avg_price_before_spp": round(float(r.realisation) / qty, 2) if r and qty else None,
                "orders_rub": round(orders_by_day.get(k, 0.0), 2),
                "drr_pct": round(spent / sales * 100, 2) if sales else None,
                "logistics": round(float(r.logistics), 2) if r else 0.0,
                "returns_rub": round(float(r.returns_rub), 2) if r else 0.0,
                "net_profit": profit_by_day.get(k),
                "storage": round(float(r.storage), 2) if r else 0.0,
            })
            cur += timedelta(days=1)
        return out

    days = await day_series(start_date, end_date)
    result: dict = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "reporting_mode": reporting_mode,
        "days": days,
    }
    if compare:
        n = (end_date - start_date).days
        prev_to = start_date - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n)
        result["prev"] = await day_series(prev_from, prev_to)
        result["prev_period"] = {"from": prev_from.isoformat(), "to": prev_to.isoformat()}
    return result


@router.get("/timeseries")
async def get_timeseries(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    return {
        "days": days,
        "mode": mode,
        "reporting_mode": reporting_mode,
        "rows": await revenue_timeseries(
            session, days=days, brands=None if nm_ids is not None else brands,
            nm_ids=nm_ids, mode=mode, reporting_mode=reporting_mode,
        ),
    }


@router.get("/top-skus")
async def get_top_skus(
    period: Literal["day", "week", "month"] = "week",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    by: Literal["revenue", "margin"] = "revenue",
    order: Literal["desc", "asc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Top SKUs. `order=asc` + `by=margin` даёт worst-margin SKUs (TASK-DEV
    quick-win 3): топ-5 проблемных карточек, которые теряют деньги."""
    p = _resolve_period(period, start_date, end_date)
    await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    return {
        "mode": mode,
        "reporting_mode": reporting_mode,
        "items": await top_skus(
            session, p, by=by, limit=limit, brands=None if nm_ids is not None else brands,
            nm_ids=nm_ids, mode=mode, order=order,
            reporting_mode=reporting_mode,
        ),
    }


@router.get("/kpi-breakdown")
async def get_kpi_breakdown(
    metric: Literal[
        "logistics_wb", "storage_wb", "commission_wb", "deduction", "penalty"
    ],
    period: Literal["day", "week", "month"] = "week",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """TASK-LEAD-055 — Top-N SKU breakdown для KPI с большой суммой удержаний.

    При клике на KPI (commission_wb / logistics_wb / storage_wb / deduction /
    penalty) в Dashboard — открывается popup с расшифровкой «куда уходят деньги».

    BUG-DEV-014 (TASK-LEAD-080): принимает `reporting_mode` (operational |
    financial) — без этого Σ breakdown ≠ Dashboard KPI в financial-режиме.
    """
    p = _resolve_period(period, start_date, end_date)
    await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    result = await compute_kpi_breakdown(
        session, p, metric=metric, brands=None if nm_ids is not None else brands,
        limit=limit, reporting_mode=reporting_mode, nm_ids=nm_ids,
    )
    return {
        "metric": result.metric,
        "label": METRIC_LABELS.get(result.metric, result.metric),
        "period_from": result.period_from,
        "period_to": result.period_to,
        "total": float(result.total),
        "items": [
            {
                "nm_id": r.nm_id,
                "vendor_code": r.vendor_code,
                "subject": r.subject,
                "brand": r.brand,
                "value": float(r.value),
                "pct_of_total": r.pct_of_total,
            }
            for r in result.items
        ],
        "truncated": result.truncated,
        "total_items": result.total_items,
        "truncated_sum": float(result.truncated_sum),
    }


@router.get("/alerts")
async def get_alerts(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return {"alerts": await collect_alerts(session, brands=brands)}


class AlertAckIn(BaseModel):
    signature: str = Field(min_length=8, max_length=64)
    alert_code: str = Field(min_length=1, max_length=64)


@router.post("/alerts/ack")
async def ack_alert(
    body: AlertAckIn,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Серверный ack для алерта (TASK-DEV-020).

    Один `(tenant_id, signature)` глушит алерт для всей команды. Если ack уже
    есть — DO UPDATE обновляет user_id + acknowledged_at (последний ack-нувший
    становится «автором»).
    """
    stmt = (
        pg_insert(AlertAcknowledgement)
        .values(
            tenant_id=user.tenant_id,
            user_id=user.id,
            alert_code=body.alert_code,
            signature=body.signature,
        )
        .on_conflict_do_update(
            constraint="uq_alert_ack_tenant_signature",
            set_={
                "user_id": user.id,
                "alert_code": body.alert_code,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    return {"ok": True, "signature": body.signature}


@router.delete("/alerts/ack/{signature}")
async def unack_alert(
    signature: str,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Снять ack — вернуть алерт в активные. Любой залогиненный юзер тенанта
    может снять чужой ack (team-shared state, аудит — через `audit_log` отдельно)."""
    await session.execute(
        delete(AlertAcknowledgement).where(
            AlertAcknowledgement.tenant_id == user.tenant_id,
            AlertAcknowledgement.signature == signature,
        )
    )
    await session.commit()
    return {"ok": True}


@router.get("/today-vs-yesterday")
async def get_today_vs_yesterday(
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Сегодня vs вчера: KPI с delta. Под "Рука на пульсе" — utility wrapper
    над compute_dashboard, считает за оба дня и считает delta_pct.

    Preliminary mode (default) использует wb_orders/wb_sales — данные
    есть в течение часа после факта. Final mode имеет лаг 1-2 дня и
    не подходит для today=сегодня.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    p_today = period_from_range(today, today)
    p_yesterday = period_from_range(yesterday, yesterday)

    store_ids = await _apply_store_filter(session, stores=stores, user=user, rbac_brands=brands)
    nm_ids = await _resolve_global_filter(
        session, glob_brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    eff_brands = None if nm_ids is not None else brands
    d_today = await compute_dashboard(
        session, p_today, brands=eff_brands, nm_ids=nm_ids, mode=mode,
        reporting_mode=reporting_mode, multi_store=bool(store_ids), store_ids=store_ids,
    )
    d_yesterday = await compute_dashboard(
        session, p_yesterday, brands=eff_brands, nm_ids=nm_ids, mode=mode,
        reporting_mode=reporting_mode, multi_store=bool(store_ids), store_ids=store_ids,
    )

    # Build delta KPIs zip-aligned by `.key`
    by_key_today = {k["key"]: k for k in d_today.get("kpis", [])}
    by_key_yesterday = {k["key"]: k for k in d_yesterday.get("kpis", [])}
    deltas = []
    for key, t_kpi in by_key_today.items():
        y_kpi = by_key_yesterday.get(key, {})
        t_val = t_kpi.get("value") or 0
        y_val = y_kpi.get("value") or 0
        delta_abs = (t_val - y_val) if isinstance(t_val, (int, float)) and isinstance(y_val, (int, float)) else None
        delta_pct = None
        if isinstance(y_val, (int, float)) and y_val:
            delta_pct = round((t_val - y_val) / y_val * 100.0, 2)
        # «Хорошо» направление: для cost/return/drr — рост = плохо; для revenue/orders/margin — рост = хорошо
        bad_growth_keys = {
            "ad_cost", "commission_wb", "logistics_wb", "storage_wb",
            "returns", "drr_pct", "drr_sales_pct",
        }
        good_direction = "up" if key not in bad_growth_keys else "down"
        deltas.append({
            "key": key,
            "label": t_kpi.get("label"),
            "tooltip": t_kpi.get("tooltip"),
            "format": t_kpi.get("format"),
            "today": t_val,
            "yesterday": y_val,
            "delta_abs": delta_abs,
            "delta_pct": delta_pct,
            "good_direction": good_direction,
        })

    return {
        "today_date": today.isoformat(),
        "yesterday_date": yesterday.isoformat(),
        "mode": mode,
        "kpis": deltas,
    }


# ── TASK-DEV-012: WeeklyChangesFeed ─────────────────────────────────────

def _weekly_changes_cache_key(tenant_id: int, brands: set[str] | None) -> str:
    """Стабильный ключ Redis: tenant + sorted brands. None (director/head) и
    set(...) (manager) дают разные кеши — это намеренно, scope разный."""
    if brands is None:
        scope = "all"
    else:
        scope = hashlib.sha1("|".join(sorted(brands)).encode("utf-8")).hexdigest()[:12]
    return f"weekly_changes:{tenant_id}:{scope}"


@router.get("/weekly-changes")
async def get_weekly_changes(
    tenant_id: int = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """3-5 (cap 8) буллетов «что изменилось с прошлой недели».

    Сторителлинг для Owner/Manager: бренды с резкими движениями выручки,
    SKU впервые жгущие рекламу >20% DRR, планы отстающие от темпа месяца.

    Кеш Redis 1 час (`weekly_changes:{tenant_id}:{scope}`). Manager и
    director получают разные ключи, scope разный.
    """
    cache_key = _weekly_changes_cache_key(tenant_id, brands)
    redis_client: redis_async.Redis | None = None
    try:
        redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
        cached = await redis_client.get(cache_key)
        if cached:
            return {"items": json.loads(cached), "cached": True}
    except Exception as e:  # noqa: BLE001 — Redis недоступен → пересчитываем без кеша
        log.warning("weekly_changes cache read failed: %s", e)
        redis_client = None

    items = await build_weekly_changes(session, brands)

    if redis_client is not None:
        try:
            await redis_client.setex(cache_key, 3600, json.dumps(items, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            log.warning("weekly_changes cache write failed: %s", e)
        finally:
            try:
                await redis_client.aclose()
            except Exception:  # noqa: BLE001
                pass

    return {"items": items, "cached": False}
