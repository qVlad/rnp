"""Analytics endpoints: ABC+XYZ classification and stockout forecast."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.abc_xyz import build_abc_xyz
from app.services.auth import current_brands_filter
from app.services.forecast import build_stockout_forecast
from app.services.supply_distribution import build_supply_distribution

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/abc-analysis")
async def abc_analysis(
    days: Annotated[int, Query(ge=7, le=365)] = 90,
    metric: Literal["revenue", "profit", "qty", "margin"] = "revenue",
    include_archived: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    return await build_abc_xyz(
        session,
        days=days,
        metric=metric,
        include_archived=include_archived,
        brands=brands,
    )


@router.get("/forecast/stockout")
async def stockout_forecast(
    velocity_window: Annotated[int, Query(ge=3, le=90)] = 14,
    target_days: Annotated[int, Query(ge=7, le=180)] = 30,
    warning_days: Annotated[float, Query(ge=1, le=30)] = 7,
    include_archived: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    return await build_stockout_forecast(
        session,
        velocity_window=velocity_window,
        target_days=target_days,
        warning_days=warning_days,
        include_archived=include_archived,
        brands=brands,
    )


@router.get("/forecast/supply-distribution")
async def supply_distribution(
    velocity_window: Annotated[int, Query(ge=3, le=90)] = 14,
    target_days: Annotated[int, Query(ge=7, le=180)] = 30,
    irp_window: Annotated[int, Query(ge=7, le=180)] = 30,
    include_archived: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    """Distribution of supply recommendation across 7 WB clusters with ИЛ/ИРП.

    Per nm:
      - velocity_per_day, recommended_total (как в /forecast/stockout)
      - il_pct (индекс локализации, 0..100)
      - clusters[]: code, label, irp_pct, stock, target_qty, deficit
    """
    return await build_supply_distribution(
        session,
        velocity_window=velocity_window,
        target_days=target_days,
        irp_window=irp_window,
        include_archived=include_archived,
        brands=brands,
    )
