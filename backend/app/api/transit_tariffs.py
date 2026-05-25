"""Тарифы транзитных направлений из ЛК WB (TASK-LEAD-078).

Источник данных: WB Tariffs API публично транзитные тарифы НЕ отдаёт. Они
доступны только в ЛК seller.wildberries.ru на странице «Поставки и заказы
→ Поставки (FBW) → Транзитные направления». Расширение РНП перехватывает
internal-fetch'и WB-фронта и постит их сюда через
`POST /api/transit-tariffs/upload`.

Endpoints:
  GET  /api/transit-tariffs                  — список тарифов tenant'а
                                                (опц. фильтр по hub/dest)
  GET  /api/transit-tariffs/lookup           — точечный lookup по паре
                                                (hub, destination), 404 если нет
  POST /api/transit-tariffs/upload           — bulk upsert от extension
                                                (director_or_head only)

Read доступен всем включая manager (brands-filter не применяется — тарифы
транзита это reference data на уровне tenant'а, не привязаны к SKU/бренду).

Write только для director/head (как и `/lk/connect` в redistribution).
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func as sa_func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbTransitTariff
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)


router = APIRouter(prefix="/api/transit-tariffs", tags=["transit-tariffs"])
logger = logging.getLogger(__name__)

# BUG-DEV-015: whitelist URL'ов из ЛК WB. Если extension прислал upload с
# URL не из этого списка — логируем warning (потенциально подозрительный
# источник: shape-парсер случайно подхватил non-tariff данные).
_SOURCE_URL_WHITELIST_RE = re.compile(
    r"^https?://([a-z0-9-]+\.)*(wildberries\.ru|wb\.ru)\b",
    re.IGNORECASE,
)


class TransitTariffRow(BaseModel):
    hub_name: str
    destination_warehouse: str
    rate_small: float | None = None
    rate_large: float | None = None
    threshold_l: float | None = None
    currency: str = "RUB"
    synced_at: str


class TransitTariffUploadItem(BaseModel):
    """BUG-DEV-015: strict-validation — `extra='forbid'` reject'ит unknown
    поля (если WB изменит shape и парсер захватит мусор, мы не сохраним
    его молча). Поля типизированы конкретно — Pydantic выкинет 422 если
    rate_small приходит строкой "abc" или dict вместо числа."""

    model_config = ConfigDict(extra="forbid", strict=False)

    hub_name: str = Field(min_length=1, max_length=255)
    destination_warehouse: str = Field(min_length=1, max_length=255)
    rate_small: float | None = Field(default=None, ge=0)
    rate_large: float | None = Field(default=None, ge=0)
    threshold_l: float | None = Field(default=1500, ge=0)
    currency: str | None = Field(default="RUB", max_length=8)


class TransitTariffUploadIn(BaseModel):
    """BUG-DEV-015: `source_url` опциональное audit-поле — URL страницы ЛК WB
    с которой extension перехватил тариф. Используется для whitelist-проверки
    и тренировки shape-парсера. `extra='forbid'` reject'ит unknown поля на
    верхнем уровне (если extension пришлёт лишний мусор — увидим 422)."""

    model_config = ConfigDict(extra="forbid")

    items: list[TransitTariffUploadItem] = Field(default_factory=list)
    source_url: str | None = Field(default=None, max_length=512)


def _row_to_dto(r: WbTransitTariff) -> dict[str, Any]:
    return {
        "hub_name": r.hub_name,
        "destination_warehouse": r.destination_warehouse,
        "rate_small": float(r.rate_small) if r.rate_small is not None else None,
        "rate_large": float(r.rate_large) if r.rate_large is not None else None,
        "threshold_l": float(r.threshold_l) if r.threshold_l is not None else None,
        "currency": r.currency,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
    }


@router.get("")
async def list_transit_tariffs(
    hub: str | None = Query(default=None),
    dest: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список тарифов транзита для текущего tenant'а.

    Опциональные фильтры: `hub` (точное совпадение, регистронезависимое),
    `dest` (то же). Доступно всем залогиненным (manager тоже видит — это
    reference data уровня tenant'а, не связано с brand/SKU).
    """
    stmt = select(WbTransitTariff).where(
        WbTransitTariff.tenant_id == user.tenant_id
    )
    if hub:
        stmt = stmt.where(WbTransitTariff.hub_name.ilike(hub))
    if dest:
        stmt = stmt.where(WbTransitTariff.destination_warehouse.ilike(dest))
    stmt = stmt.order_by(
        WbTransitTariff.hub_name,
        WbTransitTariff.destination_warehouse,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [_row_to_dto(r) for r in rows],
        "total": len(rows),
    }


@router.get("/lookup")
async def lookup_transit_tariff(
    hub: str = Query(min_length=1),
    dest: str = Query(min_length=1),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Точечный lookup по паре `(hub, destination)`. Регистронезависимо.

    Возвращает 404 если пары нет — фронт показывает manual-fallback ввод.
    """
    stmt = select(WbTransitTariff).where(
        WbTransitTariff.tenant_id == user.tenant_id,
        WbTransitTariff.hub_name.ilike(hub),
        WbTransitTariff.destination_warehouse.ilike(dest),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(404, "no transit tariff for this hub→destination pair")
    return _row_to_dto(row)


@router.post("/upload", dependencies=[Depends(require_director_or_head)])
async def upload_transit_tariffs(
    payload: TransitTariffUploadIn = Body(...),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Bulk upsert тарифов от Chrome-расширения.

    Принимает массив `{hub_name, destination_warehouse, rate_small,
    rate_large?, threshold_l?}`. Делает `ON CONFLICT DO UPDATE` по
    `(tenant, hub, destination)` с обновлением `synced_at`.

    Записи без `rate_small` И без `rate_large` (оба null) — пропускаются
    (нет смысла хранить пустую пару). Это происходит graceful — extension
    может прислать «raw» что-то парсиlessли он не понял, мы просто это
    игнорируем.
    """
    items = payload.items or []
    if not items:
        return {"inserted_or_updated": 0, "skipped": 0, "total_received": 0}

    # BUG-DEV-015: whitelist-проверка URL. Не reject'им (тариф может быть
    # валидным), но логируем warning — alertable через grep по логам и
    # audit_log (meta.suspicious_source).
    source_url = (payload.source_url or "").strip()[:512] or None
    suspicious_source = False
    if source_url and not _SOURCE_URL_WHITELIST_RE.match(source_url):
        suspicious_source = True
        logger.warning(
            "transit-tariffs upload from suspicious URL: %s (tenant=%s actor=%s)",
            source_url,
            user.tenant_id,
            user.username,
        )

    skipped = 0
    rows_to_upsert: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for it in items:
        hub = (it.hub_name or "").strip()
        dest = (it.destination_warehouse or "").strip()
        if not hub or not dest:
            skipped += 1
            continue
        if it.rate_small is None and it.rate_large is None:
            skipped += 1
            continue
        key = (hub.lower(), dest.lower())
        if key in seen_keys:
            # дедуп в одном батче — берём первое вхождение
            skipped += 1
            continue
        seen_keys.add(key)
        rows_to_upsert.append(
            {
                "tenant_id": user.tenant_id,
                "hub_name": hub,
                "destination_warehouse": dest,
                "rate_small": (
                    Decimal(str(it.rate_small)) if it.rate_small is not None else None
                ),
                "rate_large": (
                    Decimal(str(it.rate_large)) if it.rate_large is not None else None
                ),
                "threshold_l": (
                    Decimal(str(it.threshold_l)) if it.threshold_l is not None else None
                ),
                "currency": (it.currency or "RUB")[:8],
                "source_url": source_url,
            }
        )

    if not rows_to_upsert:
        return {
            "inserted_or_updated": 0,
            "skipped": skipped,
            "total_received": len(items),
        }

    # Chunked upsert (asyncpg 32767 bind-param limit). 7 fields × 1000 < 32767.
    CHUNK = 1000
    total_upserted = 0
    for i in range(0, len(rows_to_upsert), CHUNK):
        chunk = rows_to_upsert[i : i + CHUNK]
        stmt = pg_insert(WbTransitTariff).values(chunk)
        # synced_at: при INSERT возьмётся server_default=NOW(), при UPDATE
        # явно перевыставляем через func.now() — иначе старая запись
        # сохранит свой первоначальный synced_at, и UI «обновлено N ч назад»
        # будет показывать устаревшее время.
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                "tenant_id",
                "hub_name",
                "destination_warehouse",
            ],
            set_={
                "rate_small": stmt.excluded.rate_small,
                "rate_large": stmt.excluded.rate_large,
                "threshold_l": stmt.excluded.threshold_l,
                "currency": stmt.excluded.currency,
                "source_url": stmt.excluded.source_url,
                "synced_at": sa_func.now(),
            },
        )
        await session.execute(stmt)
        total_upserted += len(chunk)

    await audit_log(
        session,
        "wb_transit_tariff",
        "upload",
        entity_id=str(user.tenant_id),
        after={
            "rows": total_upserted,
            "skipped": skipped,
            "source": "chrome-extension",
            "source_url": source_url,
            "suspicious_source": suspicious_source,
        },
        actor=user.username,
    )
    await session.commit()
    return {
        "inserted_or_updated": total_upserted,
        "skipped": skipped,
        "total_received": len(items),
    }
