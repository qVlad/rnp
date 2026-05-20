"""Celery beat task: ежедневный sync WB Tariffs API (UNIT-PLAN-005).

WB-тарифы (box / pallet / commission) — глобальный справочник без ``tenant_id``;
синхронизируется один раз в день через токен любого активного селлера.

Schedule (см. ``celery_app.beat_schedule['sync-tariffs-daily']``):
  08:00 MSK ежедневно — после report_detail (04:15) и paid_storage (05:30),
  до рабочего дня.

Логика task:
  1) Берём первого tenant'а с непустым WB-токеном (тарифы одинаковые для всех).
  2) Открываем ``WbApiClient`` с этим токеном.
  3) Три вызова: ``fetch_box_tariffs``, ``fetch_pallet_tariffs``,
     ``fetch_commissions``.
  4) ``upsert_*`` функции в ``services/unit_plan_reference.py`` делают SCD-Type-2.
  5) Обновляем sync_checkpoint(entity="tariffs") для tenant'а.

Error handling:
  - ``WbCooldownActive`` → warning + skip (попробуем завтра, не retry).
  - ``WbApiError(401)`` (плохой токен) → error + skip (не retry: токен надо
    починить вручную, не циклить).
  - Прочие ошибки → ``self.retry(countdown=1800, max_retries=3)`` через 30 мин.

См. ``UNIT_PLAN.md`` §7 и ``CLAUDE.md`` § "Event loop bug".
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Tenant
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.integrations.wb.tariffs import (
    fetch_box_tariffs,
    fetch_commissions,
    fetch_pallet_tariffs,
)
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.services.unit_plan_reference import (
    upsert_box_tariffs,
    upsert_commissions,
    upsert_pallet_tariffs,
)
from app.sync.celery_app import celery_app
from app.sync.checkpoints import update_checkpoint

log = get_logger(__name__)


async def _sync_tariffs_async() -> dict[str, Any]:
    """Async core for ``sync.tariffs`` — возвращает dict со счётчиками."""
    # Импорт внутри функции из-за event-loop bug: модульный engine привязан
    # к loop'у создания, а Celery worker запускает новый loop через asyncio.run.
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(
                    Tenant.wb_token.isnot(None), Tenant.wb_token != ""
                ).limit(1)
            )
        ).scalar_one_or_none()
        if not tenant:
            log.warning("sync.tariffs: no tenants with WB token, skip")
            return {"status": "skipped", "reason": "no_tenant"}

        token = decrypt(tenant.wb_token)
        if not token:
            log.warning(
                "sync.tariffs: tenant %s wb_token failed to decrypt, skip",
                tenant.id,
            )
            return {"status": "skipped", "reason": "decrypt_failed"}

        # tenant_id нужен для update_checkpoint — SyncCheckpoint имеет
        # composite PK (tenant_id, entity); set_tenant() кладёт его в
        # session.info, откуда checkpoints.py его читает.
        set_tenant(session, tenant.id)

        today = datetime.now(timezone.utc).date()

        async with WbApiClient(token=token) as wb:
            box_records = await fetch_box_tariffs(wb, on_date=today)
            pallet_records = await fetch_pallet_tariffs(wb, on_date=today)
            commission_records = await fetch_commissions(wb)

        box = await upsert_box_tariffs(session, box_records, today)
        pallet = await upsert_pallet_tariffs(session, pallet_records, today)
        commission = await upsert_commissions(session, commission_records, today)

        total_rows = (
            box["inserted"] + box["updated"] + box["unchanged"]
            + pallet["inserted"] + pallet["updated"] + pallet["unchanged"]
            + commission["inserted"] + commission["updated"] + commission["unchanged"]
        )
        await update_checkpoint(
            session,
            "tariffs",
            rows_processed=total_rows,
            status="ok",
        )
        await session.commit()

        log.info(
            "sync.tariffs: box %d/%d/%d, pallet %d/%d/%d, commission %d/%d/%d "
            "(inserted/updated/unchanged), tenant=%s",
            box["inserted"], box["updated"], box["unchanged"],
            pallet["inserted"], pallet["updated"], pallet["unchanged"],
            commission["inserted"], commission["updated"], commission["unchanged"],
            tenant.id,
        )
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "on_date": today.isoformat(),
            "box": box,
            "pallet": pallet,
            "commission": commission,
        }


async def _mark_checkpoint_error(status: str, error: str) -> None:
    """Best-effort: записать ошибку в sync_checkpoints (на первом tenant'е с
    токеном — у нас всё равно один глобальный справочник)."""
    from app.db.session import task_session_scope  # noqa: WPS433

    try:
        async with task_session_scope() as session:
            tenant = (
                await session.execute(
                    select(Tenant).where(
                        Tenant.wb_token.isnot(None), Tenant.wb_token != ""
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if not tenant:
                return
            set_tenant(session, tenant.id)
            await update_checkpoint(
                session, "tariffs", rows_processed=0, status=status, error=error[:500]
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort logging path
        log.warning("sync.tariffs: failed to write error checkpoint: %s", exc)


@celery_app.task(
    bind=True,
    name="sync.tariffs",
    acks_late=True,
    max_retries=3,
)
def sync_tariffs(self) -> dict[str, Any]:
    """Beat task: WB Tariffs API → wb_tariff_box/pallet/commission (SCD T2).

    Schedule: 08:00 MSK daily (см. ``celery_app.beat_schedule``).
    """
    try:
        return asyncio.run(_sync_tariffs_async())
    except WbCooldownActive as exc:
        log.warning(
            "sync.tariffs: WB cooldown active (%s, %ds remaining) — skip, will retry tomorrow",
            exc.category, exc.remaining,
        )
        try:
            asyncio.run(_mark_checkpoint_error("cooldown", str(exc)))
        except Exception:  # noqa: BLE001
            pass
        return {"status": "skipped", "reason": "cooldown", "remaining_s": exc.remaining}
    except WbApiError as exc:
        if exc.status == 401:
            log.error("sync.tariffs: WB 401 (bad token) — skip, fix token manually")
            try:
                asyncio.run(_mark_checkpoint_error("unauthorized", str(exc)))
            except Exception:  # noqa: BLE001
                pass
            return {"status": "skipped", "reason": "unauthorized"}
        log.warning(
            "sync.tariffs: WbApiError %s — will retry in 30 min (attempt %s/%s)",
            exc.status, self.request.retries, self.max_retries,
        )
        try:
            asyncio.run(_mark_checkpoint_error("error", str(exc)))
        except Exception:  # noqa: BLE001
            pass
        raise self.retry(exc=exc, countdown=1800)
    except Exception as exc:
        log.exception("sync.tariffs: unexpected error — will retry in 30 min")
        try:
            asyncio.run(_mark_checkpoint_error("error", str(exc)))
        except Exception:  # noqa: BLE001
            pass
        raise self.retry(exc=exc, countdown=1800)
