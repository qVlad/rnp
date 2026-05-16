from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import current_brands_filter
from app.services.size_breakdown import build_size_breakdown
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


@router.get("/{nm_id}/sizes")
async def get_unit_sizes(
    nm_id: int,
    days_back: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Размерная разбивка для одного SKU (по `chrt_id`/`tech_size`).

    Manager видит только nm_id из своих brand_assignments. Если nm_id
    вне whitelist'а — 403.
    """
    if brands is not None:
        prod = (
            await session.execute(
                select(Product.brand).where(Product.nm_id == nm_id)
            )
        ).scalar_one_or_none()
        if prod is None or prod not in brands:
            raise HTTPException(status_code=403, detail="nm_id вне scope")
    return await build_size_breakdown(
        session,
        nm_id=nm_id,
        days_back=days_back,
        start_date=start_date,
        end_date=end_date,
    )
