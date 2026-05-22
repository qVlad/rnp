"""Celery beat task: sync WB Prices API per-tenant (TASK-LEAD-074).

В отличие от `tasks_tariffs` (глобальный справочник), prices — per-tenant:
каждый WB-кабинет имеет свой набор nm_id и свои цены. Поэтому task бегает
по всем tenant'ам с непустым `wb_token` и для каждого делает full-sync.

Schedule (см. `celery_app.beat_schedule['sync-prices-30m']`):
  каждые 30 мин. Prices API менее болтливое чем stats — можно чаще.

Логика task:
  1) Для каждого tenant'а с непустым wb_token:
  2) Открываем WbApiClient с этим токеном.
  3) `fetch_all_prices(wb)` → AsyncIterator[PriceRow].
  4) Bulk-upsert chunks по 500 в `wb_prices` (+ `wb_prices_size` если есть).
  5) Обновляем sync_checkpoint(entity="prices") для tenant'а.

Error handling: как в tasks_tariffs — `WbCooldownActive`/`WbApiError(401)`
→ skip; прочие ошибки → retry через 15 мин.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.models import Tenant, WbPrice, WbPriceSize
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.integrations.wb.prices import fetch_all_prices
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app
from app.sync.checkpoints import update_checkpoint

log = get_logger(__name__)

_CHUNK_SIZE = 500


async def _sync_tenant_prices_async(tenant_id: int) -> dict[str, Any]:
    """Async core: full-sync prices для одного tenant'а."""
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if not tenant:
            return {"status": "skipped", "reason": "tenant_not_found"}

        token = decrypt(tenant.wb_token) if tenant.wb_token else None
        if not token:
            return {"status": "skipped", "reason": "no_token"}

        set_tenant(session, tenant.id)
        synced_at = datetime.now(timezone.utc)

        rows_buffer: list[dict[str, Any]] = []
        size_rows_buffer: list[dict[str, Any]] = []
        total_rows = 0

        async def flush() -> None:
            nonlocal rows_buffer, size_rows_buffer, total_rows
            if rows_buffer:
                stmt = pg_insert(WbPrice).values(rows_buffer)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "nm_id"],
                    set_={
                        "price": stmt.excluded.price,
                        "discount_pct": stmt.excluded.discount_pct,
                        "club_discount_pct": stmt.excluded.club_discount_pct,
                        "editable_size_price": stmt.excluded.editable_size_price,
                        "currency": stmt.excluded.currency,
                        "synced_at": stmt.excluded.synced_at,
                    },
                )
                await session.execute(stmt)
                total_rows += len(rows_buffer)
                rows_buffer = []
            if size_rows_buffer:
                stmt = pg_insert(WbPriceSize).values(size_rows_buffer)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "nm_id", "tech_size"],
                    set_={
                        "price": stmt.excluded.price,
                        "discount_pct": stmt.excluded.discount_pct,
                        "synced_at": stmt.excluded.synced_at,
                    },
                )
                await session.execute(stmt)
                size_rows_buffer = []

        async with WbApiClient(token=token) as wb:
            async for row in fetch_all_prices(wb):
                rows_buffer.append(
                    {
                        "tenant_id": tenant.id,
                        "nm_id": row.nm_id,
                        "price": row.price,
                        "discount_pct": row.discount_pct,
                        "club_discount_pct": row.club_discount_pct,
                        "editable_size_price": row.editable_size_price,
                        "currency": row.currency,
                        "synced_at": synced_at,
                    }
                )
                if row.editable_size_price and row.sizes:
                    for s in row.sizes:
                        size_rows_buffer.append(
                            {
                                "tenant_id": tenant.id,
                                "nm_id": row.nm_id,
                                "tech_size": s.tech_size,
                                "price": s.price,
                                "discount_pct": s.discount_pct,
                                "synced_at": synced_at,
                            }
                        )

                if len(rows_buffer) >= _CHUNK_SIZE:
                    await flush()

            await flush()

        await update_checkpoint(
            session,
            "prices",
            rows_processed=total_rows,
            status="ok",
        )
        await session.commit()

        log.info(
            "sync.prices: tenant=%s rows=%s synced_at=%s",
            tenant.id, total_rows, synced_at.isoformat(),
        )
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "rows": total_rows,
            "synced_at": synced_at.isoformat(),
        }


async def _sync_all_tenants_async() -> dict[str, Any]:
    """Iterate over all tenants with WB token, sync each."""
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenants = (
            (
                await session.execute(
                    select(Tenant.id).where(
                        Tenant.wb_token.isnot(None), Tenant.wb_token != ""
                    )
                )
            )
            .scalars()
            .all()
        )

    results: list[dict[str, Any]] = []
    for tid in tenants:
        try:
            results.append(await _sync_tenant_prices_async(tid))
        except WbCooldownActive as exc:
            log.warning(
                "sync.prices: tenant=%s cooldown %ds, skip", tid, exc.remaining
            )
            results.append(
                {"status": "skipped", "reason": "cooldown", "tenant_id": tid}
            )
        except WbApiError as exc:
            if exc.status == 401:
                log.error("sync.prices: tenant=%s 401 (bad token), skip", tid)
                results.append(
                    {"status": "skipped", "reason": "unauthorized", "tenant_id": tid}
                )
                continue
            raise
    return {"status": "ok", "tenants_processed": len(results), "results": results}


@celery_app.task(
    bind=True,
    name="sync.prices",
    acks_late=True,
    max_retries=3,
)
def sync_wb_prices(self, tenant_id: int | None = None) -> dict[str, Any]:
    """Beat task: WB Prices API → wb_prices/wb_prices_size.

    Если `tenant_id` указан — sync только его (для ad-hoc вызовов через
    `POST /api/unit-plan/sync-prices`). Иначе — все tenants с WB-токеном.

    Schedule: каждые 30 мин (см. `celery_app.beat_schedule['sync-prices-30m']`).
    """
    try:
        if tenant_id is not None:
            return asyncio.run(_sync_tenant_prices_async(tenant_id))
        return asyncio.run(_sync_all_tenants_async())
    except WbCooldownActive as exc:
        log.warning(
            "sync.prices: WB cooldown active (%ds), will retry next tick",
            exc.remaining,
        )
        return {"status": "skipped", "reason": "cooldown", "remaining_s": exc.remaining}
    except WbApiError as exc:
        log.warning(
            "sync.prices: WbApiError %s — retry in 15 min (attempt %s/%s)",
            exc.status, self.request.retries, self.max_retries,
        )
        raise self.retry(exc=exc, countdown=900)
    except Exception as exc:
        log.exception("sync.prices: unexpected error — retry in 15 min")
        raise self.retry(exc=exc, countdown=900)
