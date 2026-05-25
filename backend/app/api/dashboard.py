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
from app.services.metrics import compute_dashboard, revenue_timeseries, top_skus
from app.services.periods import Period, get_period, period_from_range
from app.services.weekly_changes import build_weekly_changes

log = get_logger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return await compute_dashboard(
        session,
        _resolve_period(period, start_date, end_date),
        brands=brands,
        mode=mode,
        reporting_mode=reporting_mode,
    )


@router.get("/timeseries")
async def get_timeseries(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return {
        "days": days,
        "mode": mode,
        "reporting_mode": reporting_mode,
        "rows": await revenue_timeseries(
            session, days=days, brands=brands, mode=mode, reporting_mode=reporting_mode,
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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Top SKUs. `order=asc` + `by=margin` даёт worst-margin SKUs (TASK-DEV
    quick-win 3): топ-5 проблемных карточек, которые теряют деньги."""
    p = _resolve_period(period, start_date, end_date)
    return {
        "mode": mode,
        "reporting_mode": reporting_mode,
        "items": await top_skus(
            session, p, by=by, limit=limit, brands=brands, mode=mode, order=order,
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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """TASK-LEAD-055 — Top-N SKU breakdown для KPI с большой суммой удержаний.

    При клике на KPI (commission_wb / logistics_wb / storage_wb / deduction /
    penalty) в Dashboard — открывается popup с расшифровкой «куда уходят деньги».
    """
    p = _resolve_period(period, start_date, end_date)
    result = await compute_kpi_breakdown(
        session, p, metric=metric, brands=brands, limit=limit
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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
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

    d_today = await compute_dashboard(
        session, p_today, brands=brands, mode=mode, reporting_mode=reporting_mode,
    )
    d_yesterday = await compute_dashboard(
        session, p_yesterday, brands=brands, mode=mode, reporting_mode=reporting_mode,
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
