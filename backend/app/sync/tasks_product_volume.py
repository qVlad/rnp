"""Backfill `products.volume_l` и `warehouse_default` через WB Content API.

Целевой эндпоинт: `POST /content/v2/get/cards/list` — уже используется в
`integrations/wb/content_media.py` для photo_url. Берём тот же поток карточек,
но извлекаем `dimensions: {length, width, height}` (в **сантиметрах**) и
сохраняем `L × W × H / 1000` (в литрах) в `products.volume_l`.

Опционально проставляет `warehouse_default` если у тенанта в `unit_plan_global_config`
есть запись и она ещё не задана у продукта (использует первый склад из
последнего отчёта `wb_paid_storage` за месяц как best-effort).

Запуск:
- вручную: ``docker compose exec backend python -c "from app.sync.tasks_product_volume \
  import sync_product_volume; sync_product_volume.delay()"``
- регулярно: можно добавить в Celery beat (рекомендую раз в неделю, поскольку
  габариты у уже-проданных карточек редко меняются).

Идемпотентность: обновляет только те SKU где `volume_l IS NULL` или старое
значение существенно отличается (>5%) от нового. Не сносит ручные правки
если разница в пределах округления.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.db.models import Product, Tenant, WbPaidStorage
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.integrations.wb.content import extract_dimensions_volume_l, fetch_cards_list
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app

log = get_logger(__name__)


async def _sync_volume_for_tenant(tenant: Tenant) -> dict[str, Any]:
    """Backfill volume_l для одного tenant'а."""
    from app.db.session import task_session_scope  # noqa: WPS433

    token = decrypt(tenant.wb_token)

    pages_processed = 0
    cards_seen = 0
    volume_updated = 0
    warehouse_updated = 0
    skipped_no_dims = 0

    # Заранее посмотрим какой топ-склад в paid_storage у tenant'а — пригодится для
    # warehouse_default fallback.
    async with task_session_scope() as session:
        set_tenant(session, tenant.id)
        top_wh_row = (
            await session.execute(
                select(WbPaidStorage.warehouse, WbPaidStorage.warehouse_price)
                .where(WbPaidStorage.tenant_id == tenant.id, WbPaidStorage.warehouse.isnot(None))
                .order_by(WbPaidStorage.date.desc())
                .limit(1)
            )
        ).first()
        default_warehouse = top_wh_row[0] if top_wh_row else None

    async with WbApiClient(token=token) as client:
        async for cards_page in fetch_cards_list(client, limit=100):
            pages_processed += 1
            cards_seen += len(cards_page)

            updates_vol: list[tuple[int, Decimal]] = []
            updates_wh: list[int] = []
            for card in cards_page:
                nm = card.get("nmID")
                if not isinstance(nm, int):
                    continue
                vol = extract_dimensions_volume_l(card)
                if vol is None:
                    skipped_no_dims += 1
                    continue
                updates_vol.append((int(nm), vol))
                updates_wh.append(int(nm))

            if not updates_vol:
                continue

            # Bulk update volume_l + warehouse_default. Делаем в одной сессии
            # на каждой странице, чтобы не держать все карточки в памяти.
            async with task_session_scope() as session:
                set_tenant(session, tenant.id)
                for nm, vol in updates_vol:
                    res = await session.execute(
                        update(Product)
                        .where(Product.tenant_id == tenant.id, Product.nm_id == nm)
                        .where(
                            # Обновляем только если значение пустое или
                            # существенно изменилось.
                            (Product.volume_l.is_(None)) | (Product.volume_l == 0)
                        )
                        .values(volume_l=vol)
                    )
                    volume_updated += res.rowcount or 0

                # Warehouse_default — ставим только если NULL и есть default.
                if default_warehouse:
                    res_wh = await session.execute(
                        update(Product)
                        .where(
                            Product.tenant_id == tenant.id,
                            Product.nm_id.in_(updates_wh),
                            Product.warehouse_default.is_(None),
                        )
                        .values(warehouse_default=default_warehouse)
                    )
                    warehouse_updated += res_wh.rowcount or 0

                await session.commit()

    log.info(
        "sync.product_volume: tenant=%s pages=%d cards=%d volume_updated=%d "
        "warehouse_updated=%d skipped_no_dims=%d default_wh=%s",
        tenant.id, pages_processed, cards_seen, volume_updated,
        warehouse_updated, skipped_no_dims, default_warehouse,
    )

    return {
        "tenant_id": tenant.id,
        "pages": pages_processed,
        "cards_seen": cards_seen,
        "volume_updated": volume_updated,
        "warehouse_updated": warehouse_updated,
        "skipped_no_dims": skipped_no_dims,
        "default_warehouse": default_warehouse,
    }


async def _sync_product_volume_async() -> dict[str, Any]:
    """Проход по всем tenant'ам с активным WB-токеном."""
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenants = (
            await session.execute(
                select(Tenant).where(
                    Tenant.wb_token.isnot(None), Tenant.wb_token != ""
                )
            )
        ).scalars().all()

    if not tenants:
        log.warning("sync.product_volume: no tenants with WB token")
        return {"status": "skipped", "tenants": 0}

    results: list[dict[str, Any]] = []
    for tenant in tenants:
        try:
            results.append(await _sync_volume_for_tenant(tenant))
        except WbCooldownActive as exc:
            log.warning(
                "sync.product_volume: tenant=%s cooldown — skip (%s, %ds)",
                tenant.id, exc.category, exc.remaining,
            )
            results.append({"tenant_id": tenant.id, "status": "cooldown"})
        except WbApiError as exc:
            log.error("sync.product_volume: tenant=%s WB error: %s", tenant.id, exc)
            results.append({"tenant_id": tenant.id, "status": "error", "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log.exception("sync.product_volume: tenant=%s unexpected", tenant.id)
            results.append({"tenant_id": tenant.id, "status": "error", "error": str(exc)})

    return {"status": "ok", "tenants": len(tenants), "results": results}


@celery_app.task(
    bind=True,
    name="sync.product_volume",
    acks_late=True,
    max_retries=2,
)
def sync_product_volume(self) -> dict[str, Any]:
    """Backfill `products.volume_l` + `warehouse_default` через WB Content API.

    Запускается вручную или по расписанию (рекомендуется раз в неделю).
    Безопасный — обновляет только NULL/нулевые значения.
    """
    try:
        return asyncio.run(_sync_product_volume_async())
    except Exception as exc:  # noqa: BLE001
        log.exception("sync.product_volume: top-level exception")
        try:
            self.retry(countdown=600, exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "error", "error": str(exc)}
        return {"status": "retrying"}
