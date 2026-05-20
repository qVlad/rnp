"""execute_window — отправка `redistribution_tasks` в WB через Chrome-extension proxy.

После реализации Phase 3 (extension proxy) — этот модуль больше не вызывает
WB API напрямую (server-side WB-вызовы блокируются: IP-binding + JWT
in-memory у WB-фронта). Вместо этого:

  1. Group queued tasks по (src, dst, nmID)
  2. Для каждой группы pre-check src quota (kind=src) — отправляющий склад
     имеет дневной лимит на исходящие. Если 0 → group skip, иначе кешируем.
  3. Pre-check dst quota (kind=dst) — приёмник.
  4. Cap qty по min(src_quota, dst_quota) с пропорциональным масштабом.
  5. Создаём WbLkJob(op='create_order') → wait_for_job → читаем success.
  6. На success: декрементируем src_quota_cache на отправленное qty, ставим
     72h cooldown и update RedistributionTask.

Если extension оффлайн (timeout):
  - quota check не вернулся → group skip, tasks остаются queued
  - create_order не вернулся → tasks остаются queued, polling попробует снова

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


# Хардкод-fallback. Используется только если в БД tenant'а ни разу не
# проходил task/recommendation с этим office_id. Расширение возвращает
# реальные office_id в src-stocks → каждое имя, всплывавшее хотя бы раз,
# попадает в _build_office_lookup автоматически.
_HARDCODED_OFFICES: dict[str, int] = {
    "Казань": 117986,
    "Краснодар": 130744,
    "Электросталь": 120762,
    "Пенза": 50045809,
    "Самара (Новосемейкино)": 301805,
    "Екатеринбург - Перспективная 14": 300571,
    "Котовск": 301809,
    "СПБ Шушары": 50045246,
    "Шушары": 50045246,
    "Владимир": 301981,
    "Волгоград": 301983,
    "Коледино": 507,
    "Невинномысск": 208277,
    "Рязань (Тюшевское)": 301760,
    "Сарапул": 301987,
    "Тула": 206348,
}


async def _build_office_lookup(
    session: AsyncSession, *, tenant_id: int
) -> dict[str, int]:
    """Собрать словарь office_name → office_id из накопленных данных.

    Приоритет (низший → высший, последний выигрывает):
      1. Хардкод-fallback `_HARDCODED_OFFICES` — стартовое покрытие
      2. RedistributionRecommendation.from_office_id (свежие данные из
         src-stocks через extension)
      3. RedistributionTask.from_office_id (то же, но из tasks)
      4. RedistributionTask.to_office_id (только если != 0 — есть accepted
         task на этот склад, значит id точно валиден)

    Возвращает плоский dict. NULL/0 значения пропускаются.
    """
    lookup: dict[str, int] = dict(_HARDCODED_OFFICES)

    rec_rows = (
        await session.execute(
            select(
                RedistributionRecommendation.from_office_name,
                RedistributionRecommendation.from_office_id,
            )
            .where(
                RedistributionRecommendation.tenant_id == tenant_id,
                RedistributionRecommendation.from_office_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    for name, oid in rec_rows:
        if name and oid:
            lookup[name] = int(oid)

    task_src_rows = (
        await session.execute(
            select(
                RedistributionTask.from_office_name,
                RedistributionTask.from_office_id,
            )
            .where(
                RedistributionTask.tenant_id == tenant_id,
                RedistributionTask.from_office_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    for name, oid in task_src_rows:
        if name and oid:
            lookup[name] = int(oid)

    task_dst_rows = (
        await session.execute(
            select(
                RedistributionTask.to_office_name,
                RedistributionTask.to_office_id,
            )
            .where(
                RedistributionTask.tenant_id == tenant_id,
                RedistributionTask.to_office_id != 0,
            )
            .distinct()
        )
    ).all()
    for name, oid in task_dst_rows:
        if name and oid:
            lookup[name] = int(oid)

    return lookup


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

    # Резолв office_name → office_id: один проход по БД per tenant перед
    # циклом (вместо N вызовов хардкод-словаря в горячем пути).
    office_lookup = await _build_office_lookup(session, tenant_id=tenant_id)

    # Группировка по (src, dst, nm_id)
    grouped: dict[tuple[int, int, int], list[RedistributionTask]] = defaultdict(list)
    no_office: list[RedistributionTask] = []
    no_nm: list[RedistributionTask] = []
    for t in tasks:
        src = t.from_office_id or office_lookup.get(t.from_office_name)
        dst = t.to_office_id or office_lookup.get(t.to_office_name)
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

    # No-office: транзитная ошибка. Оставляем queued — следующий запуск
    # recommender'а через extension может вернуть новые офисы из src-stocks,
    # office_lookup пополнится, и в следующем polling-цикле дёрнем.
    for t in no_office:
        t.last_attempt_at = datetime.now(timezone.utc)
        t.last_response = (
            f"office_id not resolved (ждём пополнения lookup): "
            f"src={t.from_office_name!r} dst={t.to_office_name!r}"
        )
        t.attempt_count = (t.attempt_count or 0) + 1

    # No-nmID tasks → failed (recommendation удалена или orphaned —
    # nm_id неоткуда взять, retry бессмысленен).
    for t in no_nm:
        t.status = "failed"
        t.last_attempt_at = datetime.now(timezone.utc)
        t.last_response = f"nm_id not resolved (recommendation_id={t.recommendation_id})"
        t.attempt_count = (t.attempt_count or 0) + 1
        failed += 1

    # Кеш src quota per execute_window call: один офис может фигурировать
    # как source в нескольких группах (разные nm_id) — без кеша мы бы
    # делали лишние extension round-trip'ы.
    #   int >= 0  — реальная квота
    #   -1        — extension вернул error (offline / 401 / etc.), group
    #               остаётся queued
    src_quota_cache: dict[int, int] = {}

    for (src, dst, nm_id), group_tasks in grouped.items():
        # === 0. Src quota pre-check ===
        # WB отбрасывает create_order с `exceeded-quota / placement:srcOffice`
        # если на отправляющем складе исчерпан дневной лимит. Без этой
        # проверки мы тратим create_order round-trip только чтобы получить
        # ту же ошибку. Квота src восстанавливается обычно к началу нового
        # дня по МСК — task остаётся queued, polling подхватит позже.
        if src not in src_quota_cache:
            sq_job_id = await create_job(
                session,
                tenant_id=tenant_id,
                op="quota",
                params={"office_id": src, "kind": "src"},
                originator=f"execute_window:{window_dt.isoformat()}",
            )
            await session.commit()
            sq_res = await wait_for_job(
                session,
                job_id=sq_job_id,
                tenant_id=tenant_id,
                timeout_s=JOB_TIMEOUT_S,
            )
            if sq_res is None:
                src_quota_cache[src] = -1
            elif not sq_res["ok"]:
                src_quota_cache[src] = -1
                if sq_res["http_status"] == 401:
                    from app.services.redistribution.session_store import (
                        mark_needs_relogin,
                    )

                    await mark_needs_relogin(
                        session, tenant_id, "401 от src quota"
                    )
            else:
                src_quota_cache[src] = int(
                    (sq_res["data"] or {}).get("quota", 0)
                )

        src_quota = src_quota_cache[src]
        if src_quota < 0:
            log.warning(
                "execute_window: src=%d quota check failed/offline — skip group",
                src,
            )
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_response = (
                    f"src quota check unavailable (extension offline?) для "
                    f"{t.from_office_name}"
                )
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_no_extension += 1
            continue
        if src_quota < MIN_DST_QUOTA:
            log.info(
                "execute_window: src=%d quota=%d — отправляющий склад закрыт, skip group",
                src,
                src_quota,
            )
            for t in group_tasks:
                t.last_attempt_at = datetime.now(timezone.utc)
                t.last_status_code = None
                t.last_response = (
                    f"src quota = {src_quota} (склад-источник "
                    f"{t.from_office_name!r} исчерпал дневной лимит на отправку)"
                )
                t.attempt_count = (t.attempt_count or 0) + 1
                skipped_quota += 1
            continue

        # === 1. Dst quota check via extension ===
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

        # === 2. Cap by quota (min(src, dst)) ===
        by_chrt: dict[int, int] = defaultdict(int)
        for t in group_tasks:
            by_chrt[int(t.chrt_id)] += int(t.qty)
        total_requested = sum(by_chrt.values())
        effective_quota = min(dst_quota, src_quota)
        if total_requested > effective_quota:
            log.info(
                "execute_window: requested=%d > effective_quota=%d "
                "(dst=%d src=%d) — proportional cap",
                total_requested,
                effective_quota,
                dst_quota,
                src_quota,
            )
            scale = effective_quota / total_requested
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
            # Декрементируем src_quota_cache на сумму отправленного — следующая
            # группа с этим же src увидит реальный остаток (без этого две
            # группы с одним src могли совокупно превысить дневной лимит).
            shipped_qty = sum(int(it["count"]) for it in items)
            src_quota_cache[src] = max(0, src_quota_cache[src] - shipped_qty)
            log.info(
                "execute_window: ✓ accepted tenant=%d src=%d dst=%d nm=%d items=%d "
                "shipped=%d src_quota_left=%d",
                tenant_id,
                src,
                dst,
                nm_id,
                len(items),
                shipped_qty,
                src_quota_cache[src],
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
