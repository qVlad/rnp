from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import current_brands_filter
from app.services.unit_economics import build_unit_economics

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get("")
async def get_units(
    days_back: Annotated[int, Query(ge=7, le=180)] = 30,
    include_archived: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return await build_unit_economics(
        session,
        days_back=days_back,
        include_archived=include_archived,
        brands=brands,
    )
