"""Celery tasks для A/B-тестов.

Beat dispatchers (fanout per-tenant):
- `rotate_running_tests`   — каждые 15 мин: проверка триггеров и ротация фото
- `sync_abtest_stats_full` — каждые 6 ч: полный stats sync (nm-report + adv)
- `poll_abtest_budgets`    — каждые 30 мин: GET /adv/v1/budget + auto-topup

Per-tenant workers:
- `rotate_running_tests_for_tenant(tenant_id)`
- `sync_abtest_stats_for_tenant(tenant_id, quick_sync)`
- `poll_abtest_budgets_for_tenant(tenant_id)`

Self-scheduled:
- `rotation_check_one_test(abtest_id)` — точечная проверка одного теста,
  ставится в очередь с `countdown=` из `rotation._schedule_test_rotation_check`
  (TIME-триггер по точному времени, retry через 2 мин после ошибки).

Idempotency: все tasks safe для повторного выполнения (acks_late+
reject_on_worker_lost вернёт упавшие в очередь).

Queue routing:
- `default`  — rotate_running_tests, poll_abtest_budgets (light WB calls)
- `advert`   — sync_abtest_stats_full (heavy adv calls с rate-limit)
- worker-default делает фактические multipart uploads фото — у него
  смонтирован volume abtest_photos.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.db.session import task_session_scope
from app.services.abtest.budget import poll_all_budgets_for_tenant
from app.services.abtest.rotation import check_and_rotate_all, check_and_rotate_for_test
from app.services.abtest.stats import sync_running_tests_for_tenant
from app.sync.celery_app import celery_app
from app.sync.tenants import get_active_tenants

log = get_logger(__name__)


# ----------------------------------------------------------------------
# Fanout helper (copy of pattern from sync/tasks.py)
# ----------------------------------------------------------------------


async def _list_active_tenants() -> list[int]:
    async with task_session_scope() as session:
        return await get_active_tenants(session)


def _fanout(per_tenant_task, *task_args: Any) -> dict[str, Any]:
    tenants = asyncio.run(_list_active_tenants())
    if not tenants:
        log.info("[abtest] dispatcher: no active tenants")
        return {"tenants_scheduled": 0}
    for tid in tenants:
        per_tenant_task.delay(tid, *task_args)
    return {"tenants_scheduled": len(tenants), "tenant_ids": tenants}


# ----------------------------------------------------------------------
# Rotation
# ----------------------------------------------------------------------


async def _rotate_all_async() -> int:
    """Один общий async вход — `check_and_rotate_all` сама группирует тесты
    по tenant_id и открывает WbApiClient per tenant. Fanout не нужен."""
    async with task_session_scope() as session:
        return await check_and_rotate_all(session)


@celery_app.task(name="app.sync.tasks_abtest.rotate_running_tests")
def rotate_running_tests() -> int:
    """Beat (каждые 15 мин): прогон ротации по всем running тестам.
    Группировка по tenant_id и переключение WB-клиента — внутри
    `check_and_rotate_all`."""
    return asyncio.run(_rotate_all_async())


# ----------------------------------------------------------------------
# Self-scheduled per-test rotation
# ----------------------------------------------------------------------


async def _rotate_one_async(abtest_id: int) -> bool:
    async with task_session_scope() as session:
        return await check_and_rotate_for_test(session, abtest_id)


@celery_app.task(name="app.sync.tasks_abtest.rotation_check_one_test")
def rotation_check_one_test(abtest_id: int) -> bool:
    """Точечная проверка одного теста. Вызывается из
    `rotation._schedule_test_rotation_check` через `.apply_async(countdown=N)`.
    """
    return asyncio.run(_rotate_one_async(abtest_id))


# ----------------------------------------------------------------------
# Stats sync
# ----------------------------------------------------------------------


@celery_app.task(name="app.sync.tasks_abtest.sync_abtest_stats_for_tenant")
def sync_abtest_stats_for_tenant(tenant_id: int, quick_sync: bool = False) -> int:
    return asyncio.run(sync_running_tests_for_tenant(tenant_id, quick_sync=quick_sync))


@celery_app.task(name="app.sync.tasks_abtest.sync_abtest_stats_full")
def sync_abtest_stats_full() -> dict[str, Any]:
    """Beat (каждые 6 ч): полный sync (nm-report + adv + buyout topup check)."""
    return _fanout(sync_abtest_stats_for_tenant, False)


# ----------------------------------------------------------------------
# Budget polling
# ----------------------------------------------------------------------


@celery_app.task(name="app.sync.tasks_abtest.poll_abtest_budgets_for_tenant")
def poll_abtest_budgets_for_tenant(tenant_id: int) -> int:
    return asyncio.run(poll_all_budgets_for_tenant(tenant_id))


@celery_app.task(name="app.sync.tasks_abtest.poll_abtest_budgets")
def poll_abtest_budgets() -> dict[str, Any]:
    """Beat (каждые 30 мин): UPSERT баланса РК + auto-topup check."""
    return _fanout(poll_abtest_budgets_for_tenant)
