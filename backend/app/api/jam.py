"""Джем — поисковая аналитика по кластерам (10X-методика).

Источник данных:
  - Сейчас: jam_queries таблица, наполняется через Excel-импорт юзером
    (выгрузка из «Аналитики сравнения карточек» WB-кабинета).
  - В будущем: WB Jam API — отдельная подписка, целевой автосинк.

Endpoints:
  GET /api/jam/status — есть ли загруженные данные
  GET /api/jam/clusters/{nm_id} — кластеры запросов с MAX-границами
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JamQuery, Product
from app.services.auth import current_brands_filter, get_db_tenant_scoped, require_director
from app.services.jam import build_jam_clusters


router = APIRouter(prefix="/api/jam", tags=["jam"])


@router.get("/status")
async def jam_status(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сколько запросов в системе и за сколько SKU. Если 0 — show empty state."""
    total = (await session.execute(select(func.count(JamQuery.id)))).scalar() or 0
    nm_count = (
        await session.execute(select(func.count(func.distinct(JamQuery.nm_id))))
    ).scalar() or 0
    return {
        "status": "configured" if total > 0 else "empty",
        "queries_count": int(total),
        "skus_count": int(nm_count),
        "message": (
            f"Загружено {total} запросов по {nm_count} SKU."
            if total > 0
            else (
                "Нет загруженных запросов. Выгрузите ТОП-30 запросов из WB-кабинета "
                "(«Аналитика сравнения карточек») и импортируйте через Excel "
                "(/settings → Excel I/O → jam_queries)."
            )
        ),
        "docs_url": "https://seller.wildberries.ru/analytics/cards-comparison",
    }


@router.get("/clusters/{nm_id}")
async def jam_clusters(
    nm_id: int,
    days_back: Annotated[int, Query(ge=7, le=180)] = 30,
    organic_pct: Annotated[float, Query(ge=0, le=100)] = 0.0,
    target_margin_pct: Annotated[float, Query(ge=0, le=100)] = 0.0,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Кластеры поисковых запросов по SKU с MAX-границами рекламы."""
    if brands is not None:
        own = (
            await session.execute(
                select(Product.nm_id).where(
                    Product.nm_id == nm_id, Product.brand.in_(list(brands))
                )
            )
        ).scalar_one_or_none()
        if own is None:
            raise HTTPException(403, "SKU не принадлежит вашим брендам")
    res = await build_jam_clusters(
        session,
        nm_id=nm_id,
        days_back=days_back,
        organic_pct=organic_pct,
        target_margin_pct=target_margin_pct,
    )
    if not res["found"]:
        raise HTTPException(404, f"product nm_id={nm_id} not found")
    return res


@router.get("/skus")
async def jam_skus(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Список SKU для которых есть jam_queries (для UI dropdown'а)."""
    stmt = (
        select(JamQuery.nm_id, func.count().label("queries"))
        .group_by(JamQuery.nm_id)
        .order_by(func.count().desc())
    )
    if brands is not None:
        nm_sub = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        stmt = stmt.where(JamQuery.nm_id.in_(nm_sub))
    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            {"nm_id": int(r.nm_id), "queries": int(r.queries)} for r in rows
        ]
    }


@router.post("/sync-now", dependencies=[Depends(require_director)])
async def jam_sync_now(
    days_back: Annotated[int, Query(ge=7, le=180)] = 30,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Запустить WB Jam-синхронизацию руками. Возвращает результат напрямую
    (не через Celery), чтобы UI получил статус сразу. Только для director."""
    from app.services.tenant_context import get_tenant
    from app.sync.tasks import _sync_jam_async

    tid = get_tenant(session)
    if tid is None:
        raise HTTPException(400, "tenant context not set")
    return await _sync_jam_async(int(tid), days_back=days_back)


@router.get("/url")
async def jam_get_url(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    """Текущий настроенный URL для WB Jam (если задан)."""
    from app.db.models import AppSetting

    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "wb_jam_url"))
    ).scalar_one_or_none()
    return {"wb_jam_url": (row.value if row else None) or ""}


@router.put("/url", dependencies=[Depends(require_director)])
async def jam_put_url(
    payload: dict[str, str],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Установить кастомный URL endpoint для WB Jam (если дефолтные не работают)."""
    from app.db.models import AppSetting

    url = (payload.get("wb_jam_url") or "").strip()
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "wb_jam_url"))
    ).scalar_one_or_none()
    if row:
        row.value = url
    else:
        session.add(AppSetting(key="wb_jam_url", value=url))
    await session.commit()
    return {"wb_jam_url": url}
