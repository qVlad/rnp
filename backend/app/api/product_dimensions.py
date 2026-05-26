"""API `/api/product-dimensions/*` — история перемерок WB (TASK-LEAD-129).

Возвращает список последних замеров и diff-history per-SKU. Источник —
таблица `wb_product_dimensions_history`, заполняется Celery-таском
`sync.product_volume` (`backend/app/sync/tasks_product_volume.py`).

Brands-filter — manager видит только свои бренды (JOIN на products.brand).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbProductDimensionsHistory
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)

router = APIRouter(prefix="/api/product-dimensions", tags=["product-dimensions"])


def _dec_to_float(v: Decimal | None) -> float | None:
    if v is None:
        return None
    return float(v)


def _row_dict(
    h: WbProductDimensionsHistory,
    *,
    name: str | None,
    brand: str | None,
    photo_url: str | None,
) -> dict[str, Any]:
    return {
        "id": h.id,
        "nm_id": h.nm_id,
        "name": name,
        "brand": brand,
        "photo_url": photo_url,
        "length_cm": _dec_to_float(h.length_cm),
        "width_cm": _dec_to_float(h.width_cm),
        "height_cm": _dec_to_float(h.height_cm),
        "volume_l": _dec_to_float(h.volume_l),
        "prev_length_cm": _dec_to_float(h.prev_length_cm),
        "prev_width_cm": _dec_to_float(h.prev_width_cm),
        "prev_height_cm": _dec_to_float(h.prev_height_cm),
        "prev_volume_l": _dec_to_float(h.prev_volume_l),
        "change_kind": h.change_kind,
        "detected_at": h.detected_at.isoformat() if h.detected_at else None,
        "source": h.source,
    }


@router.get("/history")
async def history(
    limit: Annotated[int, Query(le=500)] = 100,
    only_changes: Annotated[bool, Query()] = True,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Последние N замеров (по всем SKU тенанта).

    - `only_changes=True` (default) — скрывает initial-snapshot'ы, показывает
      только реальные перемерки.
    - Manager видит только записи по своим брендам (JOIN на products.brand).
    """
    stmt = (
        select(
            WbProductDimensionsHistory,
            Product.subject,
            Product.brand,
            Product.photo_url,
        )
        .join(
            Product,
            (Product.tenant_id == WbProductDimensionsHistory.tenant_id)
            & (Product.nm_id == WbProductDimensionsHistory.nm_id),
        )
        .order_by(WbProductDimensionsHistory.detected_at.desc())
        .limit(limit)
    )
    if only_changes:
        stmt = stmt.where(WbProductDimensionsHistory.change_kind == "changed")
    if brands is not None:
        if not brands:
            return {"items": []}
        stmt = stmt.where(Product.brand.in_(list(brands)))

    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            _row_dict(h, name=subj, brand=brand, photo_url=photo)
            for (h, subj, brand, photo) in rows
        ]
    }


@router.get("/{nm_id}")
async def history_by_nm(
    nm_id: int,
    limit: Annotated[int, Query(le=200)] = 50,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Полная история габаритов для одной SKU (включая initial)."""
    product = (
        await session.execute(
            select(Product).where(Product.nm_id == nm_id)
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    if brands is not None and (product.brand or "") not in brands:
        raise HTTPException(status_code=403, detail="brand not in scope")

    rows = (
        await session.execute(
            select(WbProductDimensionsHistory)
            .where(WbProductDimensionsHistory.nm_id == nm_id)
            .order_by(WbProductDimensionsHistory.detected_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "product": {
            "nm_id": product.nm_id,
            "name": product.subject,
            "brand": product.brand,
            "photo_url": product.photo_url,
            "length_cm": _dec_to_float(product.length_cm),
            "width_cm": _dec_to_float(product.width_cm),
            "height_cm": _dec_to_float(product.height_cm),
            "volume_l": _dec_to_float(product.volume_l),
        },
        "items": [
            _row_dict(h, name=product.subject, brand=product.brand, photo_url=product.photo_url)
            for h in rows
        ],
    }


@router.post("/sync")
async def sync_now(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Ad-hoc trigger sync'а перемерок (director/head только).

    Запускает Celery-task `sync.product_volume` без ожидания (fire-and-forget).
    Прогресс смотреть через `/api/sync/status`.
    """
    if _user.role not in ("director", "head_of_sales"):
        raise HTTPException(status_code=403, detail="director or head required")
    from app.sync.tasks_product_volume import sync_product_volume

    result = sync_product_volume.delay()
    return {"status": "scheduled", "task_id": result.id}
