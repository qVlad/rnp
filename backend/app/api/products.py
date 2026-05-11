"""Products: list + archive/unarchive + WB photo proxy."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as cfg
from app.db.models import Product
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import current_brands_filter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])

# Photo cache TTL — 24 hours.
_PHOTO_CACHE_TTL = 86400
_PHOTO_NEGATIVE_TTL = 3600  # negative cache (404) — shorter, in case WB adds it
_PHOTO_KEY_FMT = "wb:photo:{nm_id}"
_PHOTO_NEG_FMT = "wb:photo404:{nm_id}"


def _wb_photo_urls(nm_id: int) -> list[str]:
    """Candidate WB CDN URLs for a product's main photo.

    WB partitions images across «basket-NN.wb.ru» CDNs by `nm_id // 100000`
    (vol). The mapping changes as new baskets are added; rather than maintain
    an exact range table that drifts every quarter, we pre-compute an ordered
    candidate list (most-likely basket first based on vol heuristic, then
    fallbacks) and try them in turn. First 200 wins; the result is cached for
    24 h so subsequent requests skip the probing.
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    # Heuristic primary basket (covers vol up to ~4500). The candidate list
    # then expands outward by ±1, ±2, ... so usually we hit on the 1st or
    # 2nd try.
    primary = max(1, min(28, (vol // 144) + 1))
    order: list[int] = [primary]
    for delta in range(1, 28):
        for sign in (-1, 1):
            n = primary + sign * delta
            if 1 <= n <= 28 and n not in order:
                order.append(n)
    # WB switched the CDN domain in 2026 from `wb.ru` to `wbbasket.ru`.
    # Probe new domain first across all baskets, then legacy domain as fallback.
    new_urls = [
        f"https://basket-{b:02d}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
        for b in order
    ]
    old_urls = [
        f"https://basket-{b:02d}.wb.ru/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
        for b in order
    ]
    return new_urls + old_urls


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
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
async def archive_product(nm_id: int, session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    obj.is_archived = True
    obj.archived_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.post("/{nm_id}/unarchive")
async def unarchive_product(nm_id: int, session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    obj.is_archived = False
    obj.archived_at = None
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.get("/{nm_id}/photo")
async def get_product_photo(nm_id: int) -> Response:
    """Return the WB main photo for a SKU. Cached in Redis for 24 h."""
    key = _PHOTO_KEY_FMT.format(nm_id=nm_id)
    neg_key = _PHOTO_NEG_FMT.format(nm_id=nm_id)
    r = redis_async.from_url(cfg.redis_url, decode_responses=False)
    try:
        cached = await r.get(key)
        if cached:
            return Response(
                content=cached,
                media_type="image/webp",
                headers={"Cache-Control": "public, max-age=86400", "X-Cache": "HIT"},
            )
        # Negative cache: don't hammer WB CDN if we just probed and got 404.
        if await r.get(neg_key):
            raise HTTPException(404, "WB photo not in public CDN (cached)")
        body: bytes | None = None
        last_status = 0
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            for url in _wb_photo_urls(nm_id):
                try:
                    resp = await client.get(url, headers={"User-Agent": "rnp/1.0"})
                except httpx.HTTPError:
                    continue
                last_status = resp.status_code
                if resp.status_code == 200 and resp.content:
                    body = resp.content
                    break
        if body is None:
            await r.set(neg_key, b"1", ex=_PHOTO_NEGATIVE_TTL)
            raise HTTPException(404, f"WB photo not found (last status {last_status})")
        await r.set(key, body, ex=_PHOTO_CACHE_TTL)
        return Response(
            content=body,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=86400", "X-Cache": "MISS"},
        )
    except httpx.HTTPError as e:
        log.warning("photo proxy failed for nm_id=%s: %s", nm_id, e)
        raise HTTPException(502, f"WB CDN error: {e}") from e
    finally:
        await r.aclose()
