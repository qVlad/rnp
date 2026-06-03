"""Celery beat: реальная цена покупателя с СПП из card.wb.ru (TASK-DEV-037 ph3).

Для каждого tenant'а берём nm_id его товаров, пачками тянем card.wb.ru/cards/v4
(публичный, без токена), считаем observed_spp_pct = (1−buyer/basic)×100 и
upsert в wb_card_price. /unit-plan использует это вместо ручного spp_default_pct.

Schedule: ежедневно 05:15 MSK.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.models import Product, Tenant, WbCardPrice
from app.integrations.wb.card import DEST_MOSCOW, fetch_card_prices
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app

log = get_logger(__name__)


async def _sync_tenant_card_prices_async(tenant_id: int) -> dict[str, Any]:
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if not tenant:
            return {"status": "skipped", "reason": "tenant_not_found"}
        set_tenant(session, tenant.id)

        nm_ids = (
            (
                await session.execute(
                    select(Product.nm_id).where(
                        Product.tenant_id == tenant.id,
                        Product.is_archived.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        nm_ids = [int(n) for n in nm_ids if n]
        if not nm_ids:
            return {"status": "skipped", "reason": "no_products"}

        prices = await fetch_card_prices(nm_ids, dest=DEST_MOSCOW)
        if not prices:
            return {"status": "ok", "tenant_id": tenant.id, "rows": 0}

        synced_at = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for nm, pr in prices.items():
            basic = pr.get("basic") or 0
            buyer = pr.get("buyer") or 0
            spp = round((1 - buyer / basic) * 100, 2) if basic > 0 else None
            rows.append(
                {
                    "tenant_id": tenant.id,
                    "nm_id": nm,
                    "basic_price": basic,
                    "buyer_price": buyer,
                    "observed_spp_pct": spp,
                    "dest": DEST_MOSCOW,
                    "synced_at": synced_at,
                }
            )
        for i in range(0, len(rows), 1000):
            chunk = rows[i : i + 1000]
            stmt = pg_insert(WbCardPrice).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["tenant_id", "nm_id"],
                set_={
                    "basic_price": stmt.excluded.basic_price,
                    "buyer_price": stmt.excluded.buyer_price,
                    "observed_spp_pct": stmt.excluded.observed_spp_pct,
                    "dest": stmt.excluded.dest,
                    "synced_at": stmt.excluded.synced_at,
                },
            )
            await session.execute(stmt)
        await session.commit()
        log.info("sync.card_prices: tenant=%s rows=%s", tenant.id, len(rows))
        return {"status": "ok", "tenant_id": tenant.id, "rows": len(rows)}


async def _sync_all_tenants_async() -> dict[str, Any]:
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenant_ids = (
            (await session.execute(select(Tenant.id))).scalars().all()
        )
    results = []
    for tid in tenant_ids:
        try:
            results.append(await _sync_tenant_card_prices_async(tid))
        except Exception as exc:  # noqa: BLE001
            log.exception("sync.card_prices: tenant=%s error", tid)
            results.append({"status": "error", "tenant_id": tid, "reason": str(exc)})
    return {"status": "ok", "tenants": len(tenant_ids), "results": results}


@celery_app.task(bind=True, name="sync.card_prices", acks_late=True, max_retries=2)
def sync_card_prices(self, tenant_id: int | None = None) -> dict[str, Any]:
    """Beat task: card.wb.ru → wb_card_price (реальный СПП). Daily 05:15."""
    try:
        if tenant_id is not None:
            return asyncio.run(_sync_tenant_card_prices_async(tenant_id))
        return asyncio.run(_sync_all_tenants_async())
    except Exception as exc:  # noqa: BLE001
        log.exception("sync.card_prices: unexpected — retry in 15 min")
        raise self.retry(exc=exc, countdown=900)
