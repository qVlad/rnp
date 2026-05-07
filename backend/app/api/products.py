"""Products: list + archive/unarchive."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import get_db
from app.services.auth import current_brands_filter

router = APIRouter(prefix="/api/products", tags=["products"])


def _row(p: Product) -> dict[str, Any]:
    return {
        "nm_id": p.nm_id,
        "vendor_code": p.vendor_code,
        "subject": p.subject,
        "brand": p.brand,
        "category": p.category,
        "photo_url": p.photo_url,
        "is_archived": p.is_archived,
        "archived_at": p.archived_at.isoformat() if p.archived_at else None,
        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
    }


@router.get("")
async def list_products(
    include_archived: Annotated[bool, Query()] = False,
    only_archived: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    stmt = select(Product).order_by(Product.is_archived, Product.nm_id)
    if only_archived:
        stmt = stmt.where(Product.is_archived.is_(True))
    elif not include_archived:
        stmt = stmt.where(Product.is_archived.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (Product.vendor_code.ilike(like))
            | (Product.subject.ilike(like))
            | (Product.brand.ilike(like))
        )
    if brands is not None:
        stmt = stmt.where(Product.brand.in_(list(brands)))

    rows = (await session.execute(stmt)).scalars().all()

    counts_stmt = select(
        func.count(Product.nm_id).label("total"),
        func.count(Product.nm_id).filter(Product.is_archived.is_(True)).label("archived"),
    )
    if brands is not None:
        counts_stmt = counts_stmt.where(Product.brand.in_(list(brands)))
    counts = (await session.execute(counts_stmt)).one()

    return {
        "items": [_row(r) for r in rows],
        "counts": {
            "total": int(counts.total or 0),
            "archived": int(counts.archived or 0),
            "active": int(counts.total or 0) - int(counts.archived or 0),
        },
    }


@router.post("/{nm_id}/archive")
async def archive_product(nm_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    obj.is_archived = True
    obj.archived_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.post("/{nm_id}/unarchive")
async def unarchive_product(nm_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    obj.is_archived = False
    obj.archived_at = None
    await session.commit()
    await session.refresh(obj)
    return _row(obj)
