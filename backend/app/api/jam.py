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

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AbTestPositionSnapshot, JamQuery, Product, WbSearchPosition
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
)
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


@router.get("/positions")
async def jam_positions(
    days_back: Annotated[int, Query(ge=1, le=180)] = 30,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Динамика позиций наших карточек в поиске WB (DEV-085).

    Источник — `abtest_position_snapshot` (позиции шлёт Chrome-расширение при
    заходе на www.wildberries.ru). Группируем по (nm_id, query): последняя
    позиция, дельта к первой в окне, лучшая/худшая, число замеров + таймлайн.

    Manager — только свои бренды (через Product.brand). Конкурентное сравнение
    НЕ поддерживается: расширение собирает позиции только наших карточек, не
    чужих (см. follow-up в DEV-085).
    """
    cutoff = date.today() - timedelta(days=days_back)
    stmt = (
        select(
            AbTestPositionSnapshot.nm_id,
            AbTestPositionSnapshot.query,
            AbTestPositionSnapshot.position,
            AbTestPositionSnapshot.page,
            AbTestPositionSnapshot.collected_at,
        )
        .where(func.date(AbTestPositionSnapshot.collected_at) >= cutoff)
        .order_by(AbTestPositionSnapshot.collected_at)
    )
    rows = (await session.execute(stmt)).all()

    # brand-scope: какие nm_id видит пользователь.
    allowed: set[int] | None = None
    if brands is not None:
        prod_rows = (
            await session.execute(
                select(Product.nm_id).where(Product.brand.in_(list(brands)))
            )
        ).scalars().all()
        allowed = {int(n) for n in prod_rows}

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for r in rows:
        nm = int(r.nm_id)
        if allowed is not None and nm not in allowed:
            continue
        grouped.setdefault((nm, r.query), []).append(
            {
                "dt": r.collected_at.isoformat(),
                "position": int(r.position),
                "page": int(r.page),
            }
        )

    nm_ids = sorted({k[0] for k in grouped})
    vendor: dict[int, str | None] = {}
    if nm_ids:
        for nm, vc in (
            await session.execute(
                select(Product.nm_id, Product.vendor_code).where(
                    Product.nm_id.in_(nm_ids)
                )
            )
        ).all():
            vendor[int(nm)] = vc

    items: list[dict[str, Any]] = []
    for (nm, query), series in grouped.items():
        positions = [s["position"] for s in series]
        first_pos, last_pos = positions[0], positions[-1]
        items.append(
            {
                "nm_id": nm,
                "vendor_code": vendor.get(nm),
                "query": query,
                "current_position": last_pos,
                "current_page": series[-1]["page"],
                "delta": first_pos - last_pos,  # >0 = поднялись (позиция меньше)
                "best": min(positions),
                "worst": max(positions),
                "samples": len(series),
                "timeline": series[-30:],  # последние 30 точек для спарклайна
            }
        )
    # сортировка: сначала по nm, потом по текущей позиции (лучшие сверху).
    items.sort(key=lambda x: (x["nm_id"], x["current_position"]))
    return {"days_back": days_back, "items": items, "count": len(items)}


@router.get("/competitor-queries")
async def jam_competitor_queries(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Запросы, по которым есть собранная выдача (для выбора в UI)."""
    rows = (
        await session.execute(
            select(
                WbSearchPosition.query,
                func.max(WbSearchPosition.collected_at).label("last"),
                func.count(func.distinct(WbSearchPosition.nm_id)).label("cards"),
            ).group_by(WbSearchPosition.query)
        )
    ).all()
    items = [
        {"query": r.query, "last": r.last.isoformat() if r.last else None,
         "cards": int(r.cards or 0)}
        for r in rows
    ]
    items.sort(key=lambda x: x["last"] or "", reverse=True)
    return {"items": items, "count": len(items)}


@router.get("/competitors")
async def jam_competitors(
    query: Annotated[str, Query(min_length=1)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Последний срез выдачи WB по запросу: наши карточки + конкуренты (DEV-085).

    Источник — `wb_search_position` (полный ранг шлёт расширение для запросов,
    где есть наша карточка). Берём самый свежий `collected_at` по этому запросу.
    Наши карточки помечены `is_own` + vendor_code.
    """
    last = (
        await session.execute(
            select(func.max(WbSearchPosition.collected_at)).where(
                WbSearchPosition.query == query
            )
        )
    ).scalar()
    if last is None:
        return {"query": query, "collected_at": None, "items": [], "count": 0}

    rows = (
        await session.execute(
            select(WbSearchPosition)
            .where(
                WbSearchPosition.query == query,
                WbSearchPosition.collected_at == last,
            )
            .order_by(WbSearchPosition.position)
        )
    ).scalars().all()

    own_nms = [r.nm_id for r in rows if r.is_own]
    vendor: dict[int, str | None] = {}
    if own_nms:
        for nm, vc in (
            await session.execute(
                select(Product.nm_id, Product.vendor_code).where(
                    Product.nm_id.in_(own_nms)
                )
            )
        ).all():
            vendor[int(nm)] = vc

    items = [
        {
            "nm_id": r.nm_id,
            "position": r.position,
            "page": r.page,
            "is_own": r.is_own,
            "vendor_code": vendor.get(r.nm_id) if r.is_own else None,
        }
        for r in rows
    ]
    return {
        "query": query,
        "collected_at": last.isoformat(),
        "items": items,
        "count": len(items),
        "own_count": len(own_nms),
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


@router.post("/upload-extension")
async def jam_upload_extension(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Поисковые запросы из ЛК WB через Chrome-extension (TASK-LEAD-142).

    WB endpoint `search-report/product/search-texts` (на seller-content —
    ЛК-внутренний API, токен туда не ходит, поэтому через extension на живой
    сессии). Body: `{nm_id, period_start, period_end, items: [...]}` где
    items — `data.items[]` из ответа WB (text + frequency + openCard + orders +
    addToCart).

    Маппинг в JamQuery: query=text, views=openCard, orders=orders,
    clicks=addToCart. UPSERT по (tenant, nm_id, query, period_start).
    """
    if user.role not in ("director", "head_of_sales"):
        raise HTTPException(403, "director or head required")

    nm_id = payload.get("nm_id")
    if not isinstance(nm_id, int):
        raise HTTPException(400, "nm_id обязателен (int)")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "items пуст")

    def _pd(v: Any, default: date) -> date:
        if isinstance(v, str) and len(v) >= 10:
            try:
                return date.fromisoformat(v[:10])
            except Exception:
                return default
        return default

    today = date.today()
    period_start = _pd(payload.get("period_start"), today - timedelta(days=7))
    period_end = _pd(payload.get("period_end"), today)

    def _num(d: Any) -> int:
        # WB поля вида {"current": N, ...} либо плоское число.
        if isinstance(d, dict):
            d = d.get("current")
        try:
            return int(float(d)) if d is not None else 0
        except (TypeError, ValueError):
            return 0

    upserted = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        text = it.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        values = {
            "tenant_id": user.tenant_id,
            "nm_id": nm_id,
            "query": text.strip()[:512],
            "period_start": period_start,
            "period_end": period_end,
            "orders": _num(it.get("orders")),
            "clicks": _num(it.get("addToCart")),
            "views": _num(it.get("openCard")),
            "ad_spent": 0,
        }
        ins = pg_insert(JamQuery).values(**values).on_conflict_do_update(
            index_elements=["tenant_id", "nm_id", "query", "period_start"],
            set_={
                "period_end": period_end,
                "orders": values["orders"],
                "clicks": values["clicks"],
                "views": values["views"],
            },
        )
        await session.execute(ins)
        upserted += 1
    await session.commit()

    return {
        "status": "ok",
        "nm_id": nm_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "upserted": upserted,
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
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Установить кастомный URL endpoint для WB Jam (если дефолтные не работают)."""
    from app.db.models import AppSetting

    url = (payload.get("wb_jam_url") or "").strip()
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "wb_jam_url"))
    ).scalar_one_or_none()
    if row:
        before_url = row.value
        row.value = url
        op = "update"
    else:
        before_url = None
        session.add(AppSetting(key="wb_jam_url", value=url))
        op = "create"
    await audit_log(
        session, "wb_jam_url", op,
        entity_id="wb_jam_url",
        before={"wb_jam_url": before_url} if op == "update" else None,
        after={"wb_jam_url": url},
        actor=user.username,
    )
    await session.commit()
    return {"wb_jam_url": url}
