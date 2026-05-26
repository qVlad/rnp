"""Backfill `products.volume_l` + tracking перемерок WB через Content API.

Целевой эндпоинт: `POST /content/v2/get/cards/list`. Тянем `dimensions:
{length, width, height}` (в **сантиметрах**) и сравниваем с тем что хранится
в `products.length_cm/width_cm/height_cm/volume_l`.

Логика (TASK-LEAD-129):

1. **Первый замер** (products.length_cm IS NULL) → UPDATE products +
   INSERT history-row с `change_kind='initial'`, без TG-нотификации.
2. **Уже был замер, габариты не изменились** → no-op (idempotent).
3. **Габариты изменились** → UPDATE products + INSERT history-row с
   `change_kind='changed'` + TG-broadcast директорам.

Опционально проставляет `warehouse_default` если у тенанта в `wb_paid_storage`
есть запись и она ещё не задана у продукта.

Запуск:
- вручную: ``docker compose exec backend python -c "from app.sync.tasks_product_volume \
  import sync_product_volume; sync_product_volume.delay()"``
- регулярно: см. `sync/celery_app.py` (раз в день, 06:00 MSK).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, select, update

from app.core.logging import get_logger
from app.db.models import (
    Product,
    Tenant,
    WbPaidStorage,
    WbProductDimensionsHistory,
)
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.integrations.wb.content import extract_dimensions, fetch_cards_list
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.services.tg_broadcast import broadcast_to_directors
from app.sync.celery_app import celery_app

log = get_logger(__name__)


def _fmt_dim(v: Decimal | None) -> str:
    if v is None:
        return "—"
    # Сбрасываем хвостовые нули («20.00» → «20», «20.50» → «20.5»).
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_vol(v: Decimal | None) -> str:
    if v is None:
        return "—"
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def _build_tg_message(
    *,
    nm_id: int,
    name: str | None,
    brand: str | None,
    old_l: Decimal | None,
    old_w: Decimal | None,
    old_h: Decimal | None,
    old_v: Decimal | None,
    new_l: Decimal,
    new_w: Decimal,
    new_h: Decimal,
    new_v: Decimal,
) -> str:
    title = name or f"nm_id {nm_id}"
    if brand:
        title = f"{title} • {brand}"
    old_lwh = f"{_fmt_dim(old_l)}×{_fmt_dim(old_w)}×{_fmt_dim(old_h)} см"
    new_lwh = f"{_fmt_dim(new_l)}×{_fmt_dim(new_w)}×{_fmt_dim(new_h)} см"
    delta_pct = ""
    if old_v and old_v > 0:
        pct = (float(new_v) - float(old_v)) / float(old_v) * 100.0
        arrow = "↑" if pct > 0 else "↓"
        delta_pct = f" ({arrow}{abs(pct):.1f}%)"
    return (
        f"🔧 <b>WB перемерил товар</b>\n"
        f"<b>{title}</b> (<code>{nm_id}</code>)\n"
        f"Габариты: {old_lwh} → <b>{new_lwh}</b>\n"
        f"Объём: {_fmt_vol(old_v)} → <b>{_fmt_vol(new_v)} л</b>{delta_pct}\n"
        f"\n"
        f"Проверь логистику в /unit-plan — тариф мог измениться."
    )


async def _sync_volume_for_tenant(tenant: Tenant) -> dict[str, Any]:
    """Backfill + diff-detect для одного tenant'а."""
    from app.db.session import task_session_scope  # noqa: WPS433

    token = decrypt(tenant.wb_token)

    pages_processed = 0
    cards_seen = 0
    initial_snapshots = 0
    changes_detected = 0
    warehouse_updated = 0
    skipped_no_dims = 0
    tg_sent = 0
    tg_failed = 0

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

            # Собираем извлечённые габариты для этой страницы.
            page_dims: list[tuple[int, Decimal, Decimal, Decimal, Decimal]] = []
            for card in cards_page:
                nm = card.get("nmID")
                if not isinstance(nm, int):
                    continue
                dims = extract_dimensions(card)
                if dims is None:
                    skipped_no_dims += 1
                    continue
                l, w, h, vol = dims
                page_dims.append((int(nm), l, w, h, vol))

            if not page_dims:
                continue

            # Diff против products: получаем существующие записи одной выборкой.
            nm_list = [row[0] for row in page_dims]
            async with task_session_scope() as session:
                set_tenant(session, tenant.id)
                existing_rows = (
                    await session.execute(
                        select(
                            Product.nm_id,
                            Product.length_cm,
                            Product.width_cm,
                            Product.height_cm,
                            Product.volume_l,
                            Product.subject,
                            Product.brand,
                        ).where(
                            Product.tenant_id == tenant.id,
                            Product.nm_id.in_(nm_list),
                        )
                    )
                ).all()
                existing_by_nm: dict[int, tuple] = {
                    row[0]: row for row in existing_rows
                }

                tg_messages: list[str] = []
                for nm, l, w, h, vol in page_dims:
                    existing = existing_by_nm.get(nm)
                    if existing is None:
                        # SKU неизвестна — пропускаем (создание Product'а — задача
                        # основного sync orders/sales, не этого таска).
                        continue
                    _, old_l, old_w, old_h, old_v, name, brand = existing

                    # Случай 1: initial — у нас ещё не было замеров.
                    if old_l is None and old_w is None and old_h is None:
                        await session.execute(
                            update(Product)
                            .where(Product.tenant_id == tenant.id, Product.nm_id == nm)
                            .values(
                                length_cm=l,
                                width_cm=w,
                                height_cm=h,
                                volume_l=vol if old_v is None or old_v == 0 else Product.volume_l,
                            )
                        )
                        await session.execute(
                            insert(WbProductDimensionsHistory).values(
                                tenant_id=tenant.id,
                                nm_id=nm,
                                length_cm=l,
                                width_cm=w,
                                height_cm=h,
                                volume_l=vol,
                                prev_length_cm=None,
                                prev_width_cm=None,
                                prev_height_cm=None,
                                prev_volume_l=old_v,
                                change_kind="initial",
                                source="wb_content_api",
                            )
                        )
                        initial_snapshots += 1
                        continue

                    # Случай 2: габариты не изменились — no-op.
                    # Сравниваем с tolerance 0.01 см (округление WB).
                    def _eq(a: Decimal | None, b: Decimal) -> bool:
                        if a is None:
                            return False
                        return abs(float(a) - float(b)) < 0.011

                    if _eq(old_l, l) and _eq(old_w, w) and _eq(old_h, h):
                        continue

                    # Случай 3: изменились — UPDATE + INSERT history + TG.
                    await session.execute(
                        update(Product)
                        .where(Product.tenant_id == tenant.id, Product.nm_id == nm)
                        .values(
                            length_cm=l,
                            width_cm=w,
                            height_cm=h,
                            volume_l=vol,
                        )
                    )
                    await session.execute(
                        insert(WbProductDimensionsHistory).values(
                            tenant_id=tenant.id,
                            nm_id=nm,
                            length_cm=l,
                            width_cm=w,
                            height_cm=h,
                            volume_l=vol,
                            prev_length_cm=old_l,
                            prev_width_cm=old_w,
                            prev_height_cm=old_h,
                            prev_volume_l=old_v,
                            change_kind="changed",
                            source="wb_content_api",
                        )
                    )
                    changes_detected += 1
                    tg_messages.append(
                        _build_tg_message(
                            nm_id=nm,
                            name=name,
                            brand=brand,
                            old_l=old_l,
                            old_w=old_w,
                            old_h=old_h,
                            old_v=old_v,
                            new_l=l,
                            new_w=w,
                            new_h=h,
                            new_v=vol,
                        )
                    )

                # Warehouse_default fallback для новых SKU.
                if default_warehouse:
                    res_wh = await session.execute(
                        update(Product)
                        .where(
                            Product.tenant_id == tenant.id,
                            Product.nm_id.in_(nm_list),
                            Product.warehouse_default.is_(None),
                        )
                        .values(warehouse_default=default_warehouse)
                    )
                    warehouse_updated += res_wh.rowcount or 0

                await session.commit()

                # TG-broadcast: после коммита, чтобы лог уже был в БД.
                for msg in tg_messages:
                    try:
                        result = await broadcast_to_directors(session, msg)
                        tg_sent += int(result.get("sent") or 0)
                        tg_failed += int(result.get("failed") or 0)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "tg_broadcast failed (tenant=%s): %s",
                            tenant.id, exc,
                        )
                        tg_failed += 1

    log.info(
        "sync.product_volume: tenant=%s pages=%d cards=%d initial=%d changes=%d "
        "warehouse_updated=%d skipped_no_dims=%d tg_sent=%d tg_failed=%d",
        tenant.id, pages_processed, cards_seen, initial_snapshots, changes_detected,
        warehouse_updated, skipped_no_dims, tg_sent, tg_failed,
    )

    return {
        "tenant_id": tenant.id,
        "pages": pages_processed,
        "cards_seen": cards_seen,
        "initial_snapshots": initial_snapshots,
        "changes_detected": changes_detected,
        "warehouse_updated": warehouse_updated,
        "skipped_no_dims": skipped_no_dims,
        "tg_sent": tg_sent,
        "tg_failed": tg_failed,
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
    """Backfill habarit'ов + detect перемерок WB (TASK-LEAD-129).

    Запускается по расписанию (1×/день) или вручную. При detected diff →
    history-row + Telegram-нотификация директорам.
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
