"""execute_window — отправка `redistribution_tasks` в WB через Chrome-extension proxy.

После реализации Phase 3 (extension proxy) — этот модуль больше не вызывает
WB API напрямую (server-side WB-вызовы блокируются: IP-binding + JWT
in-memory у WB-фронта). Вместо этого:

  1. Group queued tasks по (src, dst, nmID)
  2. Для каждой группы создаём WbLkJob(op='quota') → wait_for_job → читаем dst quota
  3. Cap qty по quota
  4. Создаём WbLkJob(op='create_order') → wait_for_job → читаем success
  5. Update RedistributionTask.status + RedistributionCooldown

Если extension оффлайн (timeout):
  - dst quota check не вернулся → group skip, tasks остаются queued
  - create_order не вернулся → tasks помечаем 'failed_no_extension', в next
    окне executor попробует снова

Trigger: beat-task `publish_redistribution_windows` → event-bus
`redistribution.window.open` → consumer enqueue execute_window task per tenant.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    RedistributionCooldown,
    RedistributionRecommendation,
    RedistributionTask,
)
from app.services.redistribution.extension_jobs import (
    create_job,
    wait_for_job,
)

log = logging.getLogger(__name__)


# Минимальная dst quota для попытки отправки
MIN_DST_QUOTA = 1

# Таймаут ожидания extension ответа (sec). 45 сек хватает на typical case
# (extension polls каждые 5-30 сек, content script fetch ~1-3 сек).
JOB_TIMEOUT_S = 45

# Транзитные WB-ошибки (HTTP 400/401/5xx, unexpected response shape) ретраим
# бесконечно — task остаётся `queued` пока WB не отдаст success. Типичные
# причины (exceeded-quota на srcOffice, токены LK истекли, dst quota=0)
# разрешаются сами со временем. Permanent ошибки (no_office, no_nm) идут в
# failed сразу — ретраить их бессмысленно, входные данные не изменятся.


def _office_id_lookup(office_name: str) -> int | None:
    """Резолв office_name → office_id (fallback для legacy tasks без to_office_id)."""
    KNOWN: dict[str, int] = {
        "Казань": 117986,
        "Краснодар": 130744,
        "Электросталь": 120762,
        "Пенза": 50045809,
        "Самара (Новосемейкино)": 301805,
        "Екатеринбург - Перспективная 14": 300571,
        "Котовск": 301809,
        # ─── added 2026-05-20 из stocks responses ───
        "СПБ Шушары": 50045246,
        "Шушары": 50045246,  # некоторые fronts используют короткое имя
        "Владимир": 301981,
        "Волгоград": 301983,
        "Коледино": 507,
        "Невинномысск": 208277,
        "Рязань (Тюшевское)": 301760,
        "Сарапул": 301987,
        "Тула": 206348,
    }
    return KNOWN.get(office_name)


async def execute_window_for_tenant(
    session: AsyncSession, *, tenant_id: int, window_dt: datetime
) -> dict[str, int]:
    """Главная функция: читает queued tasks tenant'а, через extension proxy
    отправляет в WB. Возвращает stats.
    """
    stmt = (
        select(RedistributionTask)
        .where(RedistributionTask.status == "queued")
        .order_by(
            RedistributionTask.priority.desc(),
            RedistributionTask.target_window_at,
        )
    )
    tasks: list[RedistributionTask] = (
        (await session.execute(stmt)).scalars().all()
    )
    if not tasks:
        return {
            "accepted": 0,
            "failed": 0,
            "skipped_quota": 0,
            "skipped_no_office": 0,
            "skipped_no_extension": 0,
            "total": 0,
        }

    # Достаём nm_id для каждой task через recommendation_id (в schema task'и
    # nm_id отсутствует — он только в recommendation). Без nmID create_order
    # отвалится с nmError на WB-стороне.
    rec_ids = [t.recommendation_id for t in tasks if t.recommendation_id]
    nm_by_rec: dict[int, int] = {}
    if rec_ids:
        rows = (
            await session.execute(
                select(
                    RedistributionRecommendation.id, RedistributionRecommendation.nm_id
                ).where(RedistributionRecommendation.id.in_(rec_ids))
            )
        ).all()
        nm_by_rec = {int(r[0]): int(r[1]) for r in rows}

    # Группировка по (src, dst, nm_id)
    grouped: dict[tuple[int, int, int], list[RedistributionTask]] = defaultdict(list)
    no_office: list[RedistributionTask] = []
    no_nm: list[RedistributionTask] = []
    for t in tasks:
        src = t.from_office_id or _office_id_lookup(t.from_office_name)
        dst = t.to_office_id or _office_id_lookup(t.to_office_name)
        if not src or not dst:
            no_office.append(t)
            continue
        nm_id = nm_by_rec.get(t.recommendation_id) if t.recommendation_id else None
        if not nm_id:
            no_nm.append(t)
            continue
        grouped[(int(src), int(dst), int(nm_id))].append(t)

    accepted = 0
    failed = 0
    skipped_quota = 0
    skipped_no_office = len(no_office)
    skipped_no_extension = 0

    # No-office tasks → failed
    for t in no_office:
        t.status = "failed"
        t.last_attempt_at = datetime.now(timezone.utc)
        t.last_response = (
            f"office_id not resolved: src={t.from_office_name!r} dst={t.to_office_name!r}"
        )
        t.attempt_count = (t.attempt_count or 0) + 1

    # No-nmID tasks → failed (recommendation orphaned или удалена)
    for t in no_nm:
        t.status = "failed"
        t.last_attempt_at = datetime.now(timezone.utc)
        t.last_response = f"nm_id not resolved (recommendation_id={t.recommendation_id})"
        t.attempt_count = (t.attempt_count or 0) + 1
        skipped_no_office += 1  # bucket в общую корзину

    for (src, dst, nm_id), group_tasks in grouped.items():
        # === 1. Quota check via extension ===
        quota_job_id = await create_job(
            session,
            tenant_id=tenant_id,
            op="quota",
            params={"office_id": dst, "kind": "dst"},
            originator=f"execute_window:{window_dt.isoformat()}",
        )
        await session.commit()
        quota_res = await wait_for_job(
            session, job_id=quota_job_id, tenant_id=tenant_id, timeout_s=JOB_TIMEOUT_S
        )
        if quota_res is None:
            log.warning(
                "execute_window: quota job %d timed out — extension offline?",
                quota_job_id,
            )
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_response = "extension offline (quota check timed out)"
                t.attempt_count = (t.attempt_count or 0) + 1
                # Не меняем status — оставляем queued для следующего окна
                skipped_no_extension += 1
            continue
        if not quota_res["ok"]:
            log.warning(
                "execute_window: quota job %d failed: %s",
                quota_job_id,
                quota_res["error"],
            )
            # 401 → токены LK устарели. Пометим needs_relogin (баннер на UI),
            # но task оставим queued — расширение обновит токены при следующем
            # визите в seller.wb.ru.
            if quota_res["http_status"] == 401:
                from app.services.redistribution.session_store import (
                    mark_needs_relogin,
                )

                await mark_needs_relogin(session, tenant_id, "401 от quota")
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_status_code = quota_res["http_status"]
                t.last_response = f"quota check failed: {quota_res['error']}"
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_no_extension += 1  # bucket: «попробуем позже»
            continue

        dst_quota = int((quota_res["data"] or {}).get("quota", 0))
        if dst_quota < MIN_DST_QUOTA:
            log.info(
                "execute_window: dst=%d quota=%d < %d — skip group",
                dst,
                dst_quota,
                MIN_DST_QUOTA,
            )
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_status_code = None
                t.last_response = f"dst quota = {dst_quota}, window closed"
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_quota += 1
            continue

        # === 2. Cap by quota ===
        by_chrt: dict[int, int] = defaultdict(int)
        for t in group_tasks:
            by_chrt[int(t.chrt_id)] += int(t.qty)
        total_requested = sum(by_chrt.values())
        if total_requested > dst_quota:
            log.info(
                "execute_window: requested=%d > dst_quota=%d — proportional cap",
                total_requested,
                dst_quota,
            )
            scale = dst_quota / total_requested
            by_chrt = {c: max(1, int(q * scale)) for c, q in by_chrt.items()}

        items = [{"chrtID": int(c), "count": int(q)} for c, q in by_chrt.items()]

        # === 3. Create order via extension ===
        order_job_id = await create_job(
            session,
            tenant_id=tenant_id,
            op="create_order",
            params={
                "src": int(src),
                "dst": int(dst),
                "nmID": int(nm_id),
                "count": items,
            },
            originator=f"execute_window:{window_dt.isoformat()}",
        )
        await session.commit()
        order_res = await wait_for_job(
            session, job_id=order_job_id, tenant_id=tenant_id, timeout_s=JOB_TIMEOUT_S
        )
        if order_res is None:
            log.warning(
                "execute_window: create_order job %d timed out", order_job_id
            )
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_response = "extension offline (create_order timed out)"
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_no_extension += 1
            continue
        if not order_res["ok"]:
            log.warning(
                "execute_window: create_order failed: %s",
                order_res["error"],
            )
            if order_res["http_status"] == 401:
                from app.services.redistribution.session_store import (
                    mark_needs_relogin,
                )

                await mark_needs_relogin(session, tenant_id, "401 от create_order")
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_status_code = order_res["http_status"]
                t.last_response = f"create_order failed: {order_res['error']}"
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_no_extension += 1
            continue

        # === 4. Success → accepted + cooldown ===
        data: Any = order_res["data"] or {}
        if isinstance(data, dict) and data.get("success"):
            now = datetime.now(timezone.utc)
            cooldown_until = now + timedelta(hours=72)
            accepted_rec_ids: set[int] = set()
            for t in group_tasks:
                t.status = "accepted"
                t.accepted_at = now
                t.last_attempt_at = now
                t.last_status_code = 200
                t.last_response = "success"
                t.attempt_count = (t.attempt_count or 0) + 1
                accepted += 1
                if t.recommendation_id:
                    accepted_rec_ids.add(int(t.recommendation_id))
                session.add(
                    RedistributionCooldown(
                        tenant_id=tenant_id,
                        chrt_id=int(t.chrt_id),
                        to_office_id=dst,
                        cooldown_until=cooldown_until,
                        last_task_id=t.id,
                    )
                )
            # Подтягиваем recommendation.status='executed' → нужно для
            # by-manager analytics (LEAD-013 group by rec.status).
            if accepted_rec_ids:
                from sqlalchemy import update as sql_update

                await session.execute(
                    sql_update(RedistributionRecommendation)
                    .where(RedistributionRecommendation.id.in_(accepted_rec_ids))
                    .values(status="executed")
                )
            log.info(
                "execute_window: ✓ accepted tenant=%d src=%d dst=%d nm=%d items=%d",
                tenant_id,
                src,
                dst,
                nm_id,
                len(items),
            )
        else:
            log.warning("execute_window: unexpected response: %r", data)
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_response = f"unexpected: {data!r}"
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_no_extension += 1

    await session.commit()
    return {
        "accepted": accepted,
        "failed": failed,
        "skipped_quota": skipped_quota,
        "skipped_no_office": skipped_no_office,
        "skipped_no_extension": skipped_no_extension,
        "total": len(tasks),
    }
