"""Product tags API (TASK-DEV-024).

Эмодзи-теги для SKU. Director CRUD'ит теги, любой залогиненный юзер
с brand-scope назначает их nm_id'ам в своей области.

Endpoints:
  GET    /api/product-tags                       — list tags + counts
  POST   /api/product-tags                       — create (director)
  PATCH  /api/product-tags/{tag_id}              — rename/recolor (director)
  DELETE /api/product-tags/{tag_id}              — delete (director, preset-нельзя)
  GET    /api/products/{nm_id}/tags              — list tag_ids на SKU
  PUT    /api/products/{nm_id}/tags              — заменить полный набор {tag_ids:[]}
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductTag, ProductTagAssignment
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
)


router = APIRouter(prefix="/api", tags=["product-tags"])


class TagIn(BaseModel):
    emoji: str = Field(default="🏷️", max_length=8)
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class TagPatch(BaseModel):
    emoji: str | None = Field(default=None, max_length=8)
    name: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)


@router.get("/product-tags")
async def list_tags(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Возвращает все теги тенанта + count назначений per-tag."""
    counts_subq = (
        select(
            ProductTagAssignment.tag_id,
            func.count(ProductTagAssignment.id).label("cnt"),
        )
        .group_by(ProductTagAssignment.tag_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(ProductTag, counts_subq.c.cnt)
            .outerjoin(counts_subq, counts_subq.c.tag_id == ProductTag.id)
            .order_by(ProductTag.is_preset.desc(), ProductTag.name)
        )
    ).all()
    return {
        "items": [
            {
                "id": t.id,
                "emoji": t.emoji,
                "name": t.name,
                "color": t.color,
                "is_preset": t.is_preset,
                "usage_count": int(cnt or 0),
            }
            for t, cnt in rows
        ]
    }


@router.post("/product-tags", dependencies=[Depends(require_director)])
async def create_tag(
    body: TagIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    tag = ProductTag(
        tenant_id=user.tenant_id,
        emoji=body.emoji,
        name=body.name,
        color=body.color,
        is_preset=False,
    )
    session.add(tag)
    try:
        await session.commit()
        await session.refresh(tag)
    except Exception as e:  # noqa: BLE001 — UNIQUE violation
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"name already exists: {e}") from e
    return {"id": tag.id, "emoji": tag.emoji, "name": tag.name, "color": tag.color}


@router.patch("/product-tags/{tag_id}", dependencies=[Depends(require_director)])
async def update_tag(
    tag_id: Annotated[int, Path(ge=1)],
    body: TagPatch,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    tag = await session.get(ProductTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="tag not found")
    if body.emoji is not None:
        tag.emoji = body.emoji
    if body.name is not None:
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    await session.commit()
    return {"ok": True}


@router.delete("/product-tags/{tag_id}", dependencies=[Depends(require_director)])
async def delete_tag(
    tag_id: Annotated[int, Path(ge=1)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    tag = await session.get(ProductTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="tag not found")
    if tag.is_preset:
        raise HTTPException(
            status_code=409,
            detail="preset tags cannot be deleted — рефер на is_preset=true",
        )
    await session.delete(tag)
    await session.commit()
    return {"ok": True}


@router.get("/products/{nm_id}/tags")
async def list_sku_tags(
    nm_id: Annotated[int, Path(ge=1)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Список tag_id'ов на SKU. Manager — только если nm_id в brand-scope."""
    if brands is not None:
        owned = (
            await session.execute(
                select(Product.nm_id).where(
                    Product.nm_id == nm_id, Product.brand.in_(list(brands))
                )
            )
        ).first()
        if not owned:
            raise HTTPException(status_code=403, detail="nm_id outside brand-scope")
    tag_ids = (
        await session.execute(
            select(ProductTagAssignment.tag_id).where(ProductTagAssignment.nm_id == nm_id)
        )
    ).scalars().all()
    return {"nm_id": nm_id, "tag_ids": list(tag_ids)}


class SkuTagsIn(BaseModel):
    tag_ids: list[int] = Field(default_factory=list)


@router.put("/products/{nm_id}/tags")
async def set_sku_tags(
    nm_id: Annotated[int, Path(ge=1)],
    body: SkuTagsIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Заменяет полный набор тегов на SKU. Manager в brand-scope."""
    if brands is not None:
        owned = (
            await session.execute(
                select(Product.nm_id).where(
                    Product.nm_id == nm_id, Product.brand.in_(list(brands))
                )
            )
        ).first()
        if not owned:
            raise HTTPException(status_code=403, detail="nm_id outside brand-scope")
    # Wipe existing + bulk insert. Простая семантика, без diff-логики.
    await session.execute(
        delete(ProductTagAssignment).where(ProductTagAssignment.nm_id == nm_id)
    )
    if body.tag_ids:
        rows = [
            {
                "tenant_id": user.tenant_id,
                "nm_id": nm_id,
                "tag_id": tid,
            }
            for tid in set(body.tag_ids)
        ]
        await session.execute(pg_insert(ProductTagAssignment).values(rows))
    await session.commit()
    return {"nm_id": nm_id, "tag_ids": list(set(body.tag_ids))}
