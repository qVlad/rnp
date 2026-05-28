"""Celery beat task: sync WB Analytics API → wb_funnel_daily (TASK-LEAD-153).

Источник: `POST /api/analytics/v3/sales-funnel/products/history` — тот же
API, на котором стоит Воронка ЛК. ВКЛЮЧАЕТ заказы в рассрочку («Оплата
частями»), в отличие от Statistics API `/supplier/orders` (там их нет
by design — см. WB_API_REFERENCE.md § /supplier/orders).

Schedule (см. `celery_app.beat_schedule['sync-funnel-daily']`):
  ежедневно 06:00 MSK (после orders/sales sync).

Логика:
  1) Для каждого tenant'а с непустым wb_token.
  2) Берём active nm_id из `products` (всё что есть в каталоге).
  3) Rolling-окно последние 90 дней (`DAYS_BACK = 90`).
  4) Chunk date-range по 30 дней (WB v3 sales-funnel практически принимает
     длинные периоды, но 30-дн куски снижают payload и риск таймаута).
  5) Chunk nm_ids по 1000 (лимит WB с декабря 2025).
  6) UPSERT в `wb_funnel_daily` по (tenant_id, nm_id, dt).

Rate limit Analytics API: 3/min, min_interval 20s — учитывается в
WbApiClient через limiter категории `analytics`. Для 29 SKU + 3 чанка
по 30 дней — ~60с на тенант.

Error handling: WbCooldownActive/401 → skip; прочие → retry 15 мин.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.models import Product, Tenant, WbFunnelDaily
from app.integrations.wb.analytics import fetch_nm_report_history
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app
from app.sync.checkpoints import update_checkpoint

log = get_logger(__name__)

DAYS_BACK = 7
# WB Analytics v3 sales-funnel — жёсткое окно **rolling 7 дней** от сегодня.
# Запрос за период старше 7 дней назад (даже chunk-by-chunk) → 400 «invalid
# start day: excess limit on days». Подобрано эмпирически 2026-05-28
# (TASK-LEAD-153). Backfill истории через API НЕВОЗМОЖЕН — данные старше
# 7 дней есть только в дашборде ЛК (интерсептором расширения, как Лента).
# Ежедневный rolling-sync накапливает локальную историю с момента старта.
DATE_CHUNK_DAYS = 7
NM_CHUNK = 1000


def _date_chunks(date_from: date, date_to: date, span: int) -> list[tuple[date, date]]:
    """Разбивает [from, to] inclusive на chunk'и по `span` дней."""
    out: list[tuple[date, date]] = []
    cur = date_from
    while cur <= date_to:
        end = min(cur + timedelta(days=span - 1), date_to)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


def _extract_history(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Достаём `history` массив из card в любой схеме (v3 / legacy)."""
    h = card.get("history")
    return h if isinstance(h, list) else []


def _extract_nm_id(card: dict[str, Any]) -> int | None:
    prod = card.get("product") or {}
    for k in ("nmId", "nmID"):
        v = prod.get(k) or card.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _parse_dt(s: Any) -> date | None:
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


async def _sync_tenant_funnel_async(
    tenant_id: int, days_back: int = DAYS_BACK
) -> dict[str, Any]:
    """Async core: sync funnel daily для одного tenant'а за `days_back` дней."""
    from app.db.session import task_session_scope

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

        # Active nm_ids = всё что есть в products каталоге тенанта.
        nm_ids_raw = (
            (
                await session.execute(
                    select(Product.nm_id).where(Product.tenant_id == tenant.id)
                )
            )
            .scalars()
            .all()
        )
        nm_ids = sorted({int(n) for n in nm_ids_raw if n})
        if not nm_ids:
            log.info("sync.funnel: tenant=%s no nm_ids, skip", tenant.id)
            return {"status": "skipped", "reason": "no_nm_ids", "tenant_id": tenant.id}

        today = date.today()
        date_from = today - timedelta(days=days_back - 1)
        date_chunks = _date_chunks(date_from, today, DATE_CHUNK_DAYS)
        nm_chunks = [
            nm_ids[i : i + NM_CHUNK] for i in range(0, len(nm_ids), NM_CHUNK)
        ]

        total_rows = 0
        async with WbApiClient(token=token) as wb:
            for d_from, d_to in date_chunks:
                for nm_chunk in nm_chunks:
                    cards = await fetch_nm_report_history(
                        wb, nm_ids=nm_chunk, date_from=d_from, date_to=d_to
                    )
                    rows: list[dict[str, Any]] = []
                    for card in cards:
                        nm = _extract_nm_id(card)
                        if nm is None:
                            continue
                        for h in _extract_history(card):
                            dt = _parse_dt(h.get("date") or h.get("dt"))
                            if dt is None:
                                continue
                            orders_count = int(
                                h.get("orderCount") or h.get("ordersCount") or 0
                            )
                            buyouts_count = int(
                                h.get("buyoutCount") or h.get("buyoutsCount") or 0
                            )
                            orders_sum = Decimal(
                                str(h.get("orderSum") or h.get("ordersSumRub") or 0)
                            )
                            open_count = h.get("openCount") or h.get("openCardCount")
                            cart_count = h.get("cartCount") or h.get("addToCartCount")
                            rows.append(
                                {
                                    "tenant_id": tenant.id,
                                    "nm_id": nm,
                                    "dt": dt,
                                    "orders_count": orders_count,
                                    "buyouts_count": buyouts_count,
                                    "orders_sum_rub": orders_sum,
                                    "open_count": int(open_count) if open_count else None,
                                    "cart_count": int(cart_count) if cart_count else None,
                                    "synced_at": synced_at,
                                }
                            )
                    if rows:
                        stmt = pg_insert(WbFunnelDaily).values(rows)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["tenant_id", "nm_id", "dt"],
                            set_={
                                "orders_count": stmt.excluded.orders_count,
                                "buyouts_count": stmt.excluded.buyouts_count,
                                "orders_sum_rub": stmt.excluded.orders_sum_rub,
                                "open_count": stmt.excluded.open_count,
                                "cart_count": stmt.excluded.cart_count,
                                "synced_at": stmt.excluded.synced_at,
                            },
                        )
                        await session.execute(stmt)
                        total_rows += len(rows)

        await update_checkpoint(
            session, "funnel_daily", rows_processed=total_rows, status="ok"
        )
        await session.commit()

        log.info(
            "sync.funnel: tenant=%s rows=%s span=%s..%s",
            tenant.id, total_rows, date_from, today,
        )
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "rows": total_rows,
            "date_from": date_from.isoformat(),
            "date_to": today.isoformat(),
        }


async def _sync_all_tenants_async(days_back: int = DAYS_BACK) -> dict[str, Any]:
    from app.db.session import task_session_scope

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
            results.append(await _sync_tenant_funnel_async(tid, days_back=days_back))
        except WbCooldownActive as exc:
            log.warning(
                "sync.funnel: tenant=%s cooldown %ds, skip", tid, exc.remaining
            )
            results.append({"status": "skipped", "reason": "cooldown", "tenant_id": tid})
        except WbApiError as exc:
            if exc.status == 401:
                log.error("sync.funnel: tenant=%s 401, skip", tid)
                results.append(
                    {"status": "skipped", "reason": "unauthorized", "tenant_id": tid}
                )
                continue
            raise
    return {"status": "ok", "tenants_processed": len(results), "results": results}


@celery_app.task(
    bind=True,
    name="sync.funnel_daily",
    acks_late=True,
    max_retries=3,
)
def sync_funnel_daily(
    self, tenant_id: int | None = None, days_back: int = DAYS_BACK
) -> dict[str, Any]:
    """WB Analytics API → wb_funnel_daily.

    Если `tenant_id` указан — sync только его (для ad-hoc / backfill).
    Schedule: ежедневно 06:00 MSK (`celery_app.beat_schedule['sync-funnel-daily']`).
    """
    try:
        if tenant_id is not None:
            return asyncio.run(_sync_tenant_funnel_async(tenant_id, days_back=days_back))
        return asyncio.run(_sync_all_tenants_async(days_back=days_back))
    except WbCooldownActive as exc:
        log.warning("sync.funnel: cooldown %ds, retry next tick", exc.remaining)
        return {"status": "skipped", "reason": "cooldown", "remaining_s": exc.remaining}
    except WbApiError as exc:
        log.warning(
            "sync.funnel: WbApiError %s — retry in 15 min (attempt %s/%s)",
            exc.status, self.request.retries, self.max_retries,
        )
        raise self.retry(exc=exc, countdown=900)
    except Exception as exc:
        log.exception("sync.funnel: unexpected — retry in 15 min")
        raise self.retry(exc=exc, countdown=900)
