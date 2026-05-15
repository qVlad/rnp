"""Checklist API — actionable per-SKU и сводный чек-лист (10X-методика)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import current_brands_filter, get_db_tenant_scoped
from app.services.checklist import build_checklist, build_summary_checklist


router = APIRouter(prefix="/api/checklist", tags=["checklist"])


@router.get("/sku/{nm_id}")
async def get_checklist(
    nm_id: int,
    days_back: Annotated[int, Query(ge=7, le=180)] = 30,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Чек-лист по одной SKU. Manager scope: nm_id должен принадлежать его брендам."""
    if brands is not None:
        # проверим что nm_id принадлежит whitelisted-бренду
        from sqlalchemy import select
        from app.db.models import Product

        own = (
            await session.execute(
                select(Product.nm_id).where(
                    Product.nm_id == nm_id, Product.brand.in_(list(brands))
                )
            )
        ).scalar_one_or_none()
        if own is None:
            raise HTTPException(403, "SKU не принадлежит вашим брендам")
    res = await build_checklist(session, nm_id=nm_id, days_back=days_back)
    if not res["found"]:
        raise HTTPException(404, f"product nm_id={nm_id} not found")
    return res


@router.get("")
async def get_summary(
    days_back: Annotated[int, Query(ge=7, le=180)] = 30,
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Сводный чек-лист — все SKU с количеством красных/жёлтых правил."""
    return await build_summary_checklist(
        session, days_back=days_back, brands=brands, limit=limit
    )
