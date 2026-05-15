from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.anomaly import collect_alerts
from app.services.auth import current_brands_filter
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
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    p = _resolve_period(period, start_date, end_date)
    return {
        "mode": mode,
        "items": await top_skus(session, p, by=by, limit=limit, brands=brands, mode=mode),
    }


@router.get("/alerts")
async def get_alerts(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return {"alerts": await collect_alerts(session, brands=brands)}
