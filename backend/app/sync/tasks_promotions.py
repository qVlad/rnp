"""Celery beat task: кэш акций WB-календаря per-tenant (TASK-DEV-037).

Раньше /promo-calculator-wb дёргал WB при каждом заходе. Теперь раз в день
синкаем акции в БД (wb_promotion + wb_promotion_nomenclature), UI читает оттуда.

Логика на tenant:
  1) list_active_promotions (today..+90d, allPromo) → список акций.
  2) bulk get_promotion_details (по 50 ID) → счётчики, type, ranging, raw.
  3) upsert wb_promotion.
  4) для НЕ-авто акций с товарами (in+notIn > 0): nomenclatures (in_action
     true+false) → normalize → пересобрать source='wb' строки. Авто-акции WB
     не отдаёт по API (422) — их товары приходят из Excel (source='excel',
     не трогаем).

Schedule: ежедневно 08:30 MSK (после tariffs 08:00). Также ad-hoc через
POST /api/promo-calculator/refresh.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.models import Tenant, WbPromotion, WbPromotionNomenclature
from app.integrations.wb.client import WbApiError, WbCooldownActive
from app.integrations.wb.promotions import (
    get_promotion_details,
    get_promotion_nomenclatures,
    list_active_promotions,
    normalize_nomenclatures,
)
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app
from app.sync.checkpoints import update_checkpoint

log = get_logger(__name__)

_CHUNK = 50


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


async def _sync_tenant_promotions_async(tenant_id: int) -> dict[str, Any]:
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
        today = date.today()
        ed = today + timedelta(days=90)

        promos = await list_active_promotions(
            token, start_date=today, end_date=ed, include_all=True
        )
        ids = [int(p["id"]) for p in promos if p.get("id")]

        # bulk details → счётчики/type/ranging/raw
        details_by_id: dict[int, dict[str, Any]] = {}
        for i in range(0, len(ids), _CHUNK):
            for d in await get_promotion_details(token, ids[i : i + _CHUNK]):
                if isinstance(d, dict):
                    did = d.get("id") or d.get("ID")
                    if did is not None:
                        details_by_id[int(did)] = d

        promo_rows: list[dict[str, Any]] = []
        for p in promos:
            pid = int(p["id"])
            d = details_by_id.get(pid, {})
            in_t = int(d.get("inPromoActionTotal") or 0)
            not_t = int(d.get("notInPromoActionTotal") or 0)
            promo_rows.append(
                {
                    "tenant_id": tenant.id,
                    "promotion_id": pid,
                    "name": p.get("name") or d.get("name"),
                    "start_dt": _parse_dt(p.get("start_date_time")),
                    "end_dt": _parse_dt(p.get("end_date_time")),
                    "promo_type": d.get("type") or p.get("type"),
                    "in_promo_count": in_t,
                    "not_in_promo_count": not_t,
                    "products_count": in_t + not_t,
                    "in_promo_action": bool(p.get("in_promo_action")),
                    "ranging": d.get("ranging"),
                    "raw": d or None,
                    "synced_at": synced_at,
                }
            )

        if promo_rows:
            for i in range(0, len(promo_rows), 500):
                chunk = promo_rows[i : i + 500]
                stmt = pg_insert(WbPromotion).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "promotion_id"],
                    set_={
                        c: getattr(stmt.excluded, c)
                        for c in (
                            "name", "start_dt", "end_dt", "promo_type",
                            "in_promo_count", "not_in_promo_count", "products_count",
                            "in_promo_action", "ranging", "raw", "synced_at",
                        )
                    },
                )
                await session.execute(stmt)

        # nomenclatures (source='wb') только для не-авто акций с товарами
        nom_rows: list[dict[str, Any]] = []
        for p in promos:
            pid = int(p["id"])
            d = details_by_id.get(pid, {})
            if (d.get("type") or "") == "auto":
                continue
            if (int(d.get("inPromoActionTotal") or 0) + int(d.get("notInPromoActionTotal") or 0)) == 0:
                continue
            suggested = await get_promotion_nomenclatures(token, pid, in_action=False)
            participating = await get_promotion_nomenclatures(token, pid, in_action=True)
            for it in normalize_nomenclatures(suggested, False) + normalize_nomenclatures(
                participating, True
            ):
                if not it.get("nmID"):
                    continue
                nom_rows.append(
                    {
                        "tenant_id": tenant.id,
                        "promotion_id": pid,
                        "nm_id": int(it["nmID"]),
                        "in_action": bool(it["inAction"]),
                        "base_price": it.get("base_price"),
                        "discount_pct": it.get("discount_pct"),
                        "current_price": it.get("current_price"),
                        "promo_price": it.get("promo_price"),
                        "plan_discount_pct": it.get("plan_discount_pct"),
                        "source": "wb",
                        "synced_at": synced_at,
                    }
                )

        # пересобираем source='wb' (excel — не трогаем)
        await session.execute(
            delete(WbPromotionNomenclature).where(
                WbPromotionNomenclature.tenant_id == tenant.id,
                WbPromotionNomenclature.source == "wb",
            )
        )
        # дедуп по (promo, nm, in_action) на всякий
        seen: set[tuple] = set()
        deduped: list[dict[str, Any]] = []
        for r in nom_rows:
            key = (r["promotion_id"], r["nm_id"], r["in_action"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        for i in range(0, len(deduped), 1000):
            await session.execute(
                pg_insert(WbPromotionNomenclature).values(deduped[i : i + 1000])
            )

        await update_checkpoint(
            session, "promotions", rows_processed=len(promo_rows), status="ok"
        )
        await session.commit()
        log.info(
            "sync.promotions: tenant=%s promos=%s nomen=%s",
            tenant.id, len(promo_rows), len(deduped),
        )
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "promos": len(promo_rows),
            "nomenclatures": len(deduped),
        }


async def _sync_all_tenants_async() -> dict[str, Any]:
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
            results.append(await _sync_tenant_promotions_async(tid))
        except (WbCooldownActive, WbApiError) as exc:
            log.warning("sync.promotions: tenant=%s skip (%s)", tid, exc)
            results.append({"status": "skipped", "tenant_id": tid, "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log.exception("sync.promotions: tenant=%s error", tid)
            results.append({"status": "error", "tenant_id": tid, "reason": str(exc)})
    return {"status": "ok", "tenants": len(tenants), "results": results}


@celery_app.task(bind=True, name="sync.promotions", acks_late=True, max_retries=3)
def sync_promotions(self, tenant_id: int | None = None) -> dict[str, Any]:
    """Beat task: WB promo-календарь → wb_promotion(_nomenclature).

    `tenant_id` задан — sync только его (ad-hoc /refresh), иначе все с токеном.
    Schedule: ежедневно 08:30 MSK (`beat_schedule['sync-promotions-daily']`).
    """
    try:
        if tenant_id is not None:
            return asyncio.run(_sync_tenant_promotions_async(tenant_id))
        return asyncio.run(_sync_all_tenants_async())
    except WbCooldownActive as exc:
        return {"status": "skipped", "reason": "cooldown", "remaining_s": exc.remaining}
    except Exception as exc:  # noqa: BLE001
        log.exception("sync.promotions: unexpected — retry in 15 min")
        raise self.retry(exc=exc, countdown=900)
