"""Season plan API — сезонный прогноз на 12 месяцев."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import current_brands_filter, get_db_tenant_scoped, require_director_or_head
from app.services.season_plan import build_season_plan


router = APIRouter(
    prefix="/api/season-plan",
    tags=["season-plan"],
    dependencies=[Depends(require_director_or_head)],
)


@router.get("")
async def get_season_plan(
    months_history: Annotated[int, Query(ge=6, le=48)] = 24,
    months_forecast: Annotated[int, Query(ge=3, le=24)] = 12,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    return await build_season_plan(
        session,
        months_history=months_history,
        months_forecast=months_forecast,
        brands=brands,
    )
