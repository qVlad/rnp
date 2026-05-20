"""Job queue для WB LK shifts API через Chrome-extension proxy.

См. описание архитектуры в `app/db/migrations/versions/0045_wb_lk_jobs.py`.

Usage (из execute_window):
    job_id = await create_job(session, op="quota", params={"office_id": 130744, "kind": "src"})
    await session.commit()  # extension не увидит job без commit
    result = await wait_for_job(session, job_id, timeout_s=30)
    if result is None:
        ...  # timeout — extension оффлайн или не отвечает
    if result["ok"]:
        quota = result["data"]["quota"]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbLkJob

log = logging.getLogger(__name__)


# Максимум сколько job'ов отдаём extension'у за один poll
PENDING_BATCH_LIMIT = 20

# Job'ы старше N секунд в статусе queued считаются «забытыми»
# (extension оффлайн или нет seller-вкладки) — execute_window timeout'ит их
# и помечает task'и как failed_no_extension чтобы повторить в следующем окне.
STALE_QUEUED_SECONDS = 60

# Job'ы в claimed дольше — extension взял но не вернул (упал или медленно)
STALE_CLAIMED_SECONDS = 120


async def create_job(
    session: AsyncSession,
    *,
    tenant_id: int,
    op: str,
    params: dict[str, Any],
    originator: str | None = None,
) -> int:
    """Создать job в очереди. Возвращает id.

    После create_job обязательно `await session.commit()` — иначе extension
    его не увидит (висит в незакоммиченной транзакции).
    """
    if op not in ("quota", "stocks", "search_nms", "create_order"):
        raise ValueError(f"unknown op: {op!r}")
    job = WbLkJob(
        tenant_id=tenant_id,
        op=op,
        params=params,
        status="queued",
        originator=originator,
    )
    session.add(job)
    await session.flush()
    return job.id


async def claim_pending(
    session: AsyncSession, *, tenant_id: int, limit: int = PENDING_BATCH_LIMIT
) -> list[WbLkJob]:
    """Атомарно взять до `limit` queued job'ов в работу. Возвращает их же
    (со status='claimed' и claimed_at=now). Вызывается из API endpoint'а
    GET /pending — extension получает фронт очереди.
    """
    now = datetime.now(timezone.utc)
    # SELECT ... FOR UPDATE SKIP LOCKED — чтобы конкурентные poll'ы (если бы
    # были) не отдавали одно и то же. Postgres-specific.
    stmt = (
        select(WbLkJob)
        .where(WbLkJob.tenant_id == tenant_id, WbLkJob.status == "queued")
        .order_by(WbLkJob.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = (await session.execute(stmt)).scalars().all()
    for j in rows:
        j.status = "claimed"
        j.claimed_at = now
    await session.flush()
    return list(rows)


async def submit_result(
    session: AsyncSession,
    *,
    tenant_id: int,
    job_id: int,
    ok: bool,
    http_status: int | None,
    data: Any | None = None,
    reason: str | None = None,
    body: str | None = None,
) -> WbLkJob:
    """Записать результат от extension. Returns updated job."""
    stmt = select(WbLkJob).where(
        and_(WbLkJob.id == job_id, WbLkJob.tenant_id == tenant_id)
    )
    j = (await session.execute(stmt)).scalar_one_or_none()
    if j is None:
        raise ValueError(f"job {job_id} not found for tenant {tenant_id}")
    if j.status in ("done", "failed"):
        # idempotent: возвращаем что есть, не перезаписываем
        return j
    j.status = "done" if ok else "failed"
    j.completed_at = datetime.now(timezone.utc)
    j.http_status = http_status
    j.result = data if isinstance(data, (dict, list)) else (
        {"value": data} if data is not None else None
    )
    j.error = reason if not ok else None
    if not ok and body:
        # сохраним body в error для отладки
        j.error = f"{j.error or ''} | body: {body[:300]}"
    await session.flush()
    return j


async def wait_for_job(
    session: AsyncSession,
    *,
    job_id: int,
    tenant_id: int,
    timeout_s: int = 30,
    poll_interval_s: float = 1.0,
) -> dict[str, Any] | None:
    """Polls БД до тех пор пока job не завершится. Возвращает:
        {"ok": bool, "http_status": int, "data": ..., "error": ...}
    или None при timeout (job так и остался queued/claimed).

    Реализация: на каждом тике делаем `session.commit()` (закрывает
    transaction → следующий SELECT откроет новую транзакцию и увидит
    обновлённую запись от extension'а). Раньше использовали
    session.expire_all() но он invalidate'ит ВСЕ ORM-объекты caller'а
    (например `group_tasks` в execute_window), что ломает их
    последующее использование → MissingGreenlet при lazy-load.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        # commit закрывает текущую транзакцию (если она открыта) →
        # следующий SELECT откроет новую транзакцию со свежим MVCC
        # snapshot. populate_existing=True заставляет ORM перечитать
        # данные из БД, минуя identity-map cache (иначе вернёт stale
        # копию с status='queued' пока сессия живёт).
        await session.commit()
        j = await session.get(
            WbLkJob, job_id, populate_existing=True
        )
        if j is None:
            return None
        if j.tenant_id != tenant_id:
            return None
        if j.status in ("done", "failed"):
            return {
                "ok": j.status == "done",
                "http_status": j.http_status,
                "data": j.result,
                "error": j.error,
            }
        await asyncio.sleep(poll_interval_s)
    log.warning(
        "wait_for_job: timeout job_id=%d tenant=%d after %ds",
        job_id,
        tenant_id,
        timeout_s,
    )
    return None


async def expire_stale_claimed(session: AsyncSession) -> int:
    """Job'ы в статусе claimed > STALE_CLAIMED_SECONDS возвращаются в queued
    (extension взял но не закрыл — упал/закрыл вкладку). Возвращает число
    re-queued.

    Запускается из beat-task раз в минуту.
    """
    now = datetime.now(timezone.utc)
    cutoff = datetime.fromtimestamp(
        now.timestamp() - STALE_CLAIMED_SECONDS, tz=timezone.utc
    )
    stmt = (
        update(WbLkJob)
        .where(WbLkJob.status == "claimed", WbLkJob.claimed_at < cutoff)
        .values(status="queued", claimed_at=None)
    )
    res = await session.execute(stmt)
    await session.flush()
    return res.rowcount or 0
