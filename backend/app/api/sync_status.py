"""Sync status endpoint — показывает что сейчас тянется из WB и когда был
последний успешный sync по каждой категории. Используется для UI-индикатора
«идёт синхронизация / cooldown / последний sync N минут назад».

Источники:
- sync_checkpoints — last_synced_at / last_status / rows_processed / last_error
- Redis: wb:cooldown:* — TTL = сколько секунд осталось до конца cooldown
- Celery inspect.active — какие таски сейчас выполняются

Полностью read-only, любой авторизованный юзер может читать. Tenant-scoped
по checkpoints (но WB cooldown — глобальный, common ресурс).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as cfg
from app.core.logging import get_logger
from app.db.models import SyncCheckpoint
from app.services.auth import CurrentUser, get_current_user, get_db_tenant_scoped

router = APIRouter(prefix="/api/sync", tags=["sync"])
log = get_logger(__name__)


# Маппинг entity → человекочитаемое название и WB category для cooldown lookup.
ENTITY_META: dict[str, dict[str, str]] = {
    "orders": {"label": "Заказы", "category": "statistics"},
    "sales": {"label": "Продажи", "category": "statistics"},
    "stocks": {"label": "Остатки", "category": "statistics"},
    "report_detail": {"label": "Финансовый отчёт", "category": "finance"},
    "ad_campaigns": {"label": "Рекламные кампании", "category": "advert"},
    "ad_stats": {"label": "Статистика рекламы", "category": "advert"},
    "ad_campaign_details": {"label": "Детали кампаний", "category": "advert"},
    "paid_storage": {"label": "Платное хранение", "category": "analytics"},
    "redeem_notifications": {"label": "Уведомления о выкупе", "category": "documents"},
    "offset_acts": {"label": "Акты взаимозачёта", "category": "documents"},
    "product_photos": {"label": "Фото товаров", "category": "content"},
    "jam": {"label": "Поисковые запросы", "category": "analytics"},
}

WB_CATEGORIES = ["statistics", "finance", "advert", "analytics", "documents", "content"]


async def _get_cooldowns() -> dict[str, int]:
    """Pull wb:cooldown:* TTLs from Redis. Returns {category: seconds_remaining}."""
    out: dict[str, int] = {}
    try:
        r = redis_async.from_url(cfg.redis_url, decode_responses=True)
        for cat in WB_CATEGORIES:
            try:
                ttl = await r.ttl(f"wb:cooldown:{cat}")
                if ttl and ttl > 0:
                    out[cat] = int(ttl)
            except Exception:
                continue
        await r.aclose()
    except Exception as e:
        log.warning("sync_status: redis unreachable for cooldowns: %s", e)
    return out


def _task_tenant_id(name: str, args: list[Any]) -> int | None:
    """Извлечь tenant_id из args таска.

    Для per-tenant тасков (`*_for_tenant`) tenant_id всегда первый позиционный
    аргумент. Для глобальных dispatcher'ов (sync_orders, sync_sales и т.д.)
    args пустой — возвращаем None (показывается во всех tenant'ах).
    """
    if not args:
        return None
    if "_for_tenant" not in name:
        return None
    try:
        return int(args[0])
    except (TypeError, ValueError, IndexError):
        return None


def _get_active_celery_tasks(filter_tenant_id: int | None) -> list[dict[str, Any]]:
    """Inspect celery workers for active tasks. Filtered by tenant_id —
    per-tenant таски без совпадения tenant_id скрываются; глобальные
    dispatcher'ы (без args) показываются всем (они касаются всех tenant'ов).
    """
    try:
        from app.sync.celery_app import celery_app

        i = celery_app.control.inspect(timeout=1.5)
        active = i.active() or {}
        out: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).timestamp()
        for worker, tasks in active.items():
            for t in tasks or []:
                ts = t.get("time_start") or 0
                started_ago = max(0, int(now - ts)) if ts else None
                name = t.get("name", "")
                # Только sync-таски нам интересны
                if not name.startswith("app.sync.tasks."):
                    continue
                args = t.get("args") or []
                task_tid = _task_tenant_id(name, args)
                if (
                    filter_tenant_id is not None
                    and task_tid is not None
                    and task_tid != filter_tenant_id
                ):
                    continue  # task другого tenant'а — не показываем
                short = name.replace("app.sync.tasks.", "")
                out.append(
                    {
                        "name": short,
                        "id": t.get("id"),
                        "worker": worker,
                        "started_ago_s": started_ago,
                        "args": args,
                        "tenant_id": task_tid,
                    }
                )
        return out
    except Exception as e:
        log.warning("sync_status: celery inspect failed: %s", e)
        return []


@router.get("/status")
async def get_sync_status(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Полный snapshot статуса синхронизации для текущего tenant'а.

    Возвращает:
    - entities: checkpoints ИМЕННО этого tenant'а (last_synced/status/rows/error)
    - cooldowns: активные WB cooldown'ы (общие для всех tenant'ов — WB rate-limit
                 глобален per-токен, но у нас один shared WB per category)
    - active_tasks: per-tenant таски этого tenant'а + глобальные dispatcher'ы
    - is_syncing: bool — есть ли активный sync-таск (для точки в sidebar)
    """
    # SyncCheckpoint НЕ наследуется от TenantScopedMixin, поэтому
    # do_orm_execute event listener его не фильтрует. Фильтруем явно.
    tenant_id = user.tenant_id
    rows = (await session.execute(
        select(SyncCheckpoint)
        .where(SyncCheckpoint.tenant_id == tenant_id)
        .order_by(SyncCheckpoint.entity)
    )).scalars().all()

    now = datetime.now(timezone.utc)
    entities: list[dict[str, Any]] = []
    seen = set()
    for r in rows:
        meta = ENTITY_META.get(r.entity, {"label": r.entity, "category": ""})
        last = r.last_synced_at
        age_s = int((now - last).total_seconds()) if last else None
        entities.append({
            "entity": r.entity,
            "label": meta["label"],
            "category": meta["category"],
            "last_synced_at": last.isoformat() if last else None,
            "age_s": age_s,
            "status": r.last_status,
            "rows_processed": r.rows_processed,
            "error": r.last_error,
        })
        seen.add(r.entity)

    # Добавим entities из ENTITY_META, для которых ещё нет checkpoint'а (никогда не запускались)
    for entity, meta in ENTITY_META.items():
        if entity in seen:
            continue
        entities.append({
            "entity": entity,
            "label": meta["label"],
            "category": meta["category"],
            "last_synced_at": None,
            "age_s": None,
            "status": None,
            "rows_processed": 0,
            "error": None,
        })

    entities.sort(key=lambda e: e["label"])

    # cooldowns
    cooldowns_raw = await _get_cooldowns()
    cooldowns = [
        {"category": cat, "remaining_s": sec, "label": _category_label(cat)}
        for cat, sec in sorted(cooldowns_raw.items(), key=lambda kv: -kv[1])
    ]

    # active tasks (фильтрованные по tenant_id)
    active = _get_active_celery_tasks(filter_tenant_id=tenant_id)

    return {
        "entities": entities,
        "cooldowns": cooldowns,
        "active_tasks": active,
        "is_syncing": len(active) > 0,
        "server_time": now.isoformat(),
        "tenant_id": tenant_id,
    }


def _category_label(cat: str) -> str:
    return {
        "statistics": "Статистика (orders/sales/stocks)",
        "finance": "Финансы (отчёты)",
        "advert": "Реклама",
        "analytics": "Аналитика",
        "documents": "Документы",
        "content": "Контент",
    }.get(cat, cat)
