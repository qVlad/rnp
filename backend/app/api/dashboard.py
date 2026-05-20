from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertAcknowledgement
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.anomaly import collect_alerts
from app.services.metrics import compute_dashboard, revenue_timeseries, top_skus
from app.services.periods import Period, get_period, period_from_range

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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return await compute_dashboard(
        session,
        _resolve_period(period, start_date, end_date),
        brands=brands,
        mode=mode,
    )


@router.get("/timeseries")
async def get_timeseries(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return {
        "days": days,
        "mode": mode,
        "rows": await revenue_timeseries(session, days=days, brands=brands, mode=mode),
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
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Top SKUs. `order=asc` + `by=margin` даёт worst-margin SKUs (TASK-DEV
    quick-win 3): топ-5 проблемных карточек, которые теряют деньги."""
    p = _resolve_period(period, start_date, end_date)
    return {
        "mode": mode,
        "items": await top_skus(
            session, p, by=by, limit=limit, brands=brands, mode=mode, order=order,
        ),
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

    d_today = await compute_dashboard(session, p_today, brands=brands, mode=mode)
    d_yesterday = await compute_dashboard(session, p_yesterday, brands=brands, mode=mode)

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
