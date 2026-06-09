from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import CurrentUser, current_brands_filter, get_current_user
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.tenant_context import set_tenant_filter
from app.services.size_breakdown import build_size_breakdown
from app.services.unit_economics import build_unit_economics

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get("")
async def get_units(
    days_back: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    glob_brands: Annotated[str | None, Query(alias="brands")] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    # DEV-062 Phase C: свод по магазинам (≥2 кабинета) → расширить ORM-фильтр.
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    # DEV-062: глобальные фильтры → nm_ids (RBAC учтён через rbac_brands).
    nm_ids = await resolve_nm_scope(
        session, brands=glob_brands, categories=categories, groups=groups,
        articles=articles, rbac_brands=brands,
    )
    return await build_unit_economics(
        session,
        days_back=days_back,
        start_date=start_date,
        end_date=end_date,
        include_archived=include_archived,
        brands=None if nm_ids is not None else brands,
        nm_ids=nm_ids,
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
