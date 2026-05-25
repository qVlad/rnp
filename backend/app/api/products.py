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
from app.services.audit import audit_log
from app.services.auth import CurrentUser, get_current_user, get_db_tenant_scoped
from app.services.auth import current_brands_filter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])

# Photo cache TTL — 24 hours.
_PHOTO_CACHE_TTL = 86400
_PHOTO_NEGATIVE_TTL = 3600  # negative cache (404) — shorter, in case WB adds it
_PHOTO_KEY_FMT = "wb:photo:{nm_id}"
_PHOTO_NEG_FMT = "wb:photo404:{nm_id}"


_MAX_BASKET = 36  # WB добавляет новые корзины (>=29 для свежих nm_id из 2025-2026).


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
    # Heuristic primary basket. Эмпирическая формула WB по vol — расширена до
    # basket 36 (свежие SKU из 2025-2026 живут в 29-36; default-формула их
    # промахивала, давая 404).
    primary = max(1, min(_MAX_BASKET, (vol // 144) + 1))
    order: list[int] = [primary]
    for delta in range(1, _MAX_BASKET):
        for sign in (-1, 1):
            n = primary + sign * delta
            if 1 <= n <= _MAX_BASKET and n not in order:
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
    # Для A/B-теста: подгружать только карточки с заполненным photo_url.
    # Это эквивалент wbab-поведения, где picker не показывает SKU без фото
    # на WB CDN. Без фильтра picker показывал бы карточки, для которых
    # "Подгрузить текущее" вернёт 404.
    has_photo: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    stmt = select(Product).order_by(Product.is_archived, Product.nm_id)
    if only_archived:
        stmt = stmt.where(Product.is_archived.is_(True))
    elif not include_archived:
        stmt = stmt.where(Product.is_archived.is_(False))
    if has_photo:
        stmt = stmt.where(Product.photo_url.is_not(None), Product.photo_url != "")
    if search:
        like = f"%{search}%"
        conditions = (
            Product.vendor_code.ilike(like)
            | Product.subject.ilike(like)
            | Product.brand.ilike(like)
        )
        # Числовой ввод → также матчим точное nm_id (ILIKE по integer не работает,
        # поэтому отдельная ветка). Это нужно для ProductPicker, который после
        # selection повторно ходит по `?search={nm_id}` чтобы подтянуть детали.
        if search.isdigit():
            conditions = conditions | (Product.nm_id == int(search))
        stmt = stmt.where(conditions)
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


@router.get("/{nm_id}/traffic-estimate")
async def traffic_estimate(
    nm_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Оценка дневного трафика карточки за последние 7 дней.

    Используется в форме создания A/B-теста чтобы предупредить когда
    выборка не наберётся в разумный срок. Источник — nm-report
    sales-funnel (поле openCardCount = открытия карточки = impressions
    в нашей терминологии).

    Возвращает:
    - avg_daily_impressions: int | null — среднее в день; None если данных нет
    - days_observed: int — за сколько дней есть данные (для интерпретации)
    - source: "nm-report" | "wb-error" | "no-token"
    - http_status: int | null — для понятной ошибки в UI
    """
    from datetime import date, timedelta
    from app.integrations.wb.analytics import fetch_nm_report_history
    from app.integrations.wb.client import WbApiError
    from app.sync.tenants import wb_client_for_tenant

    prod = await session.get(Product, nm_id)
    if prod is None:
        raise HTTPException(404, "product not found")
    if brands is not None and (prod.brand or "") not in brands:
        raise HTTPException(403, "not in your brands")

    try:
        wb_client = await wb_client_for_tenant(session, prod.tenant_id)
    except RuntimeError:
        return {
            "avg_daily_impressions": None,
            "days_observed": 0,
            "source": "no-token",
            "http_status": None,
        }

    today = date.today()
    week_ago = today - timedelta(days=7)
    try:
        async with wb_client as wb:
            cards = await fetch_nm_report_history(
                wb, nm_ids=[nm_id], date_from=week_ago, date_to=today,
                aggregation_level="day",
            )
    except WbApiError as e:
        return {
            "avg_daily_impressions": None,
            "days_observed": 0,
            "source": "wb-error",
            "http_status": e.status,
        }
    except Exception:
        return {
            "avg_daily_impressions": None,
            "days_observed": 0,
            "source": "wb-error",
            "http_status": None,
        }

    if not cards:
        return {
            "avg_daily_impressions": 0,
            "days_observed": 0,
            "source": "nm-report",
            "http_status": 200,
        }
    card = next(
        (c for c in cards if int((c.get("product") or {}).get("nmId") or c.get("nmID") or c.get("nmId") or 0) == nm_id),
        None,
    )
    if card is None:
        return {"avg_daily_impressions": 0, "days_observed": 0, "source": "nm-report", "http_status": 200}

    history = card.get("history") or []
    # WB v3 (2026): поле "openCount" (было "openCardCount" в v2).
    days = len(history)
    total = sum(
        int(d.get("openCount") or d.get("openCardCount") or 0)
        for d in history
    )
    avg = int(total / days) if days > 0 else None
    return {
        "avg_daily_impressions": avg,
        "days_observed": days,
        "source": "nm-report",
        "http_status": 200,
    }


@router.get("/{nm_id}/transit-suggest")
async def transit_suggest(
    nm_id: int,
    weeks: Annotated[int, Query(ge=1, le=12)] = 4,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """TASK-LEAD-071: подсказки для TransitCalculator при выборе SKU.

    Возвращает:
    - volume_l: float | null — `products.volume_l` (из миграции 0041).
    - avg_weekly_orders: float | null — среднее количество заказов в неделю
      за последние N недель (по умолчанию 4) из `wb_orders` (без отменённых).
    - suggested_units: int | null — `round(avg_weekly_orders * weeks)`, чтобы
      покрыть период `weeks` недель.
    - weeks_window: int — фактическое окно (echo от параметра).
    """
    from datetime import timedelta
    from app.db.models import WbOrder

    prod = await session.get(Product, nm_id)
    if prod is None:
        raise HTTPException(404, "product not found")
    if brands is not None and (prod.brand or "") not in brands:
        raise HTTPException(403, "not in your brands")

    volume_l: float | None = None
    if prod.volume_l is not None:
        try:
            volume_l = float(prod.volume_l)
        except (TypeError, ValueError):
            volume_l = None

    window_days = weeks * 7
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    cnt_stmt = (
        select(func.count(WbOrder.srid))
        .where(
            WbOrder.nm_id == nm_id,
            WbOrder.order_dt >= since,
            WbOrder.is_cancel.is_(False),
        )
    )
    total = (await session.execute(cnt_stmt)).scalar_one() or 0
    avg_weekly = float(total) / float(weeks) if weeks > 0 else None
    suggested_units = int(round(avg_weekly * weeks)) if avg_weekly else None
    # avg_weekly = total / weeks; suggested_units = total (по сути). Возвращаем
    # отдельно avg_weekly для UI-подсказки «в среднем X в неделю».
    return {
        "nm_id": nm_id,
        "volume_l": volume_l,
        "avg_weekly_orders": avg_weekly,
        "suggested_units": suggested_units,
        "weeks_window": weeks,
        "total_orders_window": int(total),
    }


@router.post("/{nm_id}/archive")
async def archive_product(
    nm_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    was_archived = obj.is_archived
    obj.is_archived = True
    obj.archived_at = datetime.now(timezone.utc)
    if not was_archived:
        await audit_log(
            session, "products", "update",
            entity_id=str(nm_id),
            before={"is_archived": False},
            after={"is_archived": True, "archived_at": obj.archived_at.isoformat()},
            actor=user.username,
            comment="archive",
        )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.post("/{nm_id}/unarchive")
async def unarchive_product(
    nm_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(Product, nm_id)
    if not obj:
        raise HTTPException(404, "product not found")
    was_archived = obj.is_archived
    obj.is_archived = False
    obj.archived_at = None
    if was_archived:
        await audit_log(
            session, "products", "update",
            entity_id=str(nm_id),
            before={"is_archived": True},
            after={"is_archived": False},
            actor=user.username,
            comment="unarchive",
        )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.get("/{nm_id}/photo")
async def get_product_photo(nm_id: int) -> Response:
    """Return the WB main photo for a SKU. Cached in Redis for 24 h.

    Priority of URL sources:
      1. Redis cache (fastest) — 24h TTL.
      2. `Product.photo_url` из БД (заполняется через sync_product_photos
         раз в сутки через WB Content API) — 1 запрос, ~100мс.
      3. Heuristic basket-CDN probing (12+ кандидатов) — fallback ~700мс
         для SKU без content-API синки.
    """
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

        # (2) Prefer Product.photo_url из БД — заполнено через WB Content API.
        # admin scope (без set_tenant) — Product.tenant_id фильтр не применяется,
        # SELECT возвращает первый матч; для photo-proxy этого достаточно
        # т.к. nm_id уникален в WB и фото у всех tenant'ов одинаковое.
        from app.db.session import SessionLocal
        from app.db.models import Product

        db_url: str | None = None
        async with SessionLocal() as session:
            from sqlalchemy import select as _sel
            row = (
                await session.execute(_sel(Product.photo_url).where(Product.nm_id == nm_id))
            ).first()
            if row and row[0]:
                db_url = row[0]

        body: bytes | None = None
        last_status = 0
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            # (2) Сначала пробуем известный URL из БД.
            if db_url:
                try:
                    resp = await client.get(db_url, headers={"User-Agent": "rnp/1.0"})
                    last_status = resp.status_code
                    if resp.status_code == 200 and resp.content:
                        body = resp.content
                except httpx.HTTPError:
                    pass
            # (3) Fallback — перебор basket-CDN'ов.
            if body is None:
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
