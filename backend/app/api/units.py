from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import current_brands_filter
from app.services.unit_economics import build_unit_economics

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get("")
async def get_units(
    days_back: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    return await build_unit_economics(
        session,
        days_back=days_back,
        start_date=start_date,
        end_date=end_date,
        include_archived=include_archived,
        brands=brands,
    )
