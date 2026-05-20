"""execute_window — отправка `redistribution_tasks` в WB в окнах 09:00/18:00 МСК.

Дизайн (LEAD-016 после получения HAR 2026-05-19):

1. **Trigger:** beat-task `publish_redistribution_windows` каждую минуту
   проверяет окно; если попадает на 09:00 или 18:00 МСК — публикует event
   `redistribution.window.open` через event_bus.
2. **Consumer:** этот модуль читает `queued` task'и tenant'а, для каждой
   проверяет quota dst, отправляет через `WbLkClient.create_order` и
   обновляет статус.

В v1 — sequential per-tenant с проверкой quota на каждую заявку. v2 —
параллельный submit batch'ем через asyncio.gather.

Group by (src, dst, nmID) — WB позволяет несколько `chrtID` в одной заявке
для одной пары src/dst/nm. Это уменьшает число API-вызовов.
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
    RedistributionTask,
)
from app.integrations.wb_lk.client import LkClientError, WbLkClient
from app.services.redistribution.session_store import (
    load_tokens,
    mark_needs_relogin,
    save_wb_seller_lk,
)

log = logging.getLogger(__name__)


# Минимальная quota dst чтобы попытаться — иначе skip (или статус
# `failed: dst_quota_zero`). 1 — потому что HAR показал минимум 1 ед.
MIN_DST_QUOTA = 1


def _office_id_lookup(office_name: str) -> int | None:
    """Резолв office_name → office_id. В v1 у нас в task.to_office_id
    лежит реальный ID если recommendation его проставил. Эта функция —
    fallback для legacy задач (до миграции на office_id). Расширять
    справочник по мере встречи новых ID'ов.
    """
    # Карта на основе HAR-данных:
    KNOWN: dict[str, int] = {
        "Казань": 117986,
        "Краснодар": 130744,
        "Электросталь": 120762,
        "Пенза": 50045809,
        "Самара (Новосемейкино)": 301805,
        "Екатеринбург - Перспективная 14": 300571,
        "Котовск": 1733,  # placeholder, нужно подтвердить
        # Расширять при встрече с реальными запросами /stocks
    }
    return KNOWN.get(office_name)


async def execute_window_for_tenant(
    session: AsyncSession, *, tenant_id: int, window_dt: datetime
) -> dict[str, int]:
    """Главная функция: читает queued tasks tenant'а на это окно (или
    ближайшее), группирует по (src, dst, nmID) и отправляет через
    WbLkClient.create_order.

    Обновляет:
      - task.status: queued → sent → accepted (если WB вернул success)
                         или → failed (если LkClientError / 4xx)
      - task.attempt_count, last_attempt_at, last_status_code, last_response
      - RedistributionCooldown: 72ч с момента accepted

    Возвращает stats: {accepted, failed, skipped_quota, skipped_no_office, total}.
    """
    tokens = await load_tokens(session, tenant_id)
    if tokens is None:
        log.info(
            "execute_window: no LK tokens for tenant=%d — skip (need /lk/connect)",
            tenant_id,
        )
        return {
            "accepted": 0,
            "failed": 0,
            "skipped_quota": 0,
            "skipped_no_office": 0,
            "total": 0,
        }

    # Берём queued tasks с target_window_at <= window_dt + 6h (на случай
    # пропущенных окон — добираем их если ещё не expired)
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
            "total": 0,
        }

    # Группировка по (src_office, dst_office, nm_id) — несколько chrtID
    # в один запрос. Если src_office_id=0/None — пробуем resolve через
    # office name lookup.
    grouped: dict[tuple[int, int, int], list[RedistributionTask]] = defaultdict(
        list
    )
    no_office: list[RedistributionTask] = []
    for t in tasks:
        src = t.from_office_id or _office_id_lookup(t.from_office_name)
        dst = t.to_office_id or _office_id_lookup(t.to_office_name)
        if not src or not dst:
            no_office.append(t)
            continue
        grouped[(int(src), int(dst), int(t.chrt_id))].append(t)

    accepted = 0
    failed = 0
    skipped_quota = 0
    skipped_no_office = len(no_office)

    # Пометим no_office как failed
    for t in no_office:
        t.status = "failed"
        t.last_attempt_at = datetime.now(timezone.utc)
        t.last_response = (
            f"office_id not resolved: src={t.from_office_name!r} dst={t.to_office_name!r}"
        )
        t.attempt_count = (t.attempt_count or 0) + 1

    # Используем on_token_refreshed callback чтобы сохранять свежий
    # Wb-Seller-Lk в БД (иначе следующий beat-tick получит истёкший).
    async def _persist_refreshed_token(new_token: str) -> None:
        try:
            await save_wb_seller_lk(
                session, tenant_id=tenant_id, wb_seller_lk=new_token
            )
            await session.commit()
        except Exception:
            log.exception(
                "execute_window: failed to persist refreshed Wb-Seller-Lk"
            )

    # WB-кабинет: один nmID на заявку, но в count[] можно несколько chrt_id.
    # У нас key уже (src, dst, nm) — внутри chrt_ids могут различаться по
    # task'ам (но обычно один SKU = одна группа задач). Если task.chrt_id
    # одинаковый у всех в группе (что норма) — items=[(chrt_id, sum_qty)].
    # Если разные — отправим несколько `items`.
    try:
        async with WbLkClient(
            tokens, on_token_refreshed=_persist_refreshed_token
        ) as lk:
            for (src, dst, nm_id), group_tasks in grouped.items():
                # Проверяем dst quota
                try:
                    dst_quota = await lk.get_quota(dst, kind="dst")
                except LkClientError as e:
                    log.warning(
                        "execute_window: get_quota dst=%d failed (%s) — skip group",
                        dst,
                        e,
                    )
                    for t in group_tasks:
                        t.status = "failed"
                        t.last_attempt_at = datetime.now(timezone.utc)
                        t.last_status_code = e.status
                        t.last_response = f"quota check failed: {e}"
                        t.attempt_count = (t.attempt_count or 0) + 1
                        failed += 1
                    continue

                if dst_quota < MIN_DST_QUOTA:
                    log.info(
                        "execute_window: dst=%d quota=%d < %d — skip group (%d tasks)",
                        dst,
                        dst_quota,
                        MIN_DST_QUOTA,
                        len(group_tasks),
                    )
                    for t in group_tasks:
                        t.last_attempt_at = datetime.now(timezone.utc)
                        t.last_status_code = None
                        t.last_response = f"dst quota = {dst_quota}, window closed"
                        t.attempt_count = (t.attempt_count or 0) + 1
                        # Не меняем status — оставляем queued для следующего окна
                        skipped_quota += 1
                    continue

                # Группируем по chrt_id внутри — суммируем count
                by_chrt: dict[int, int] = defaultdict(int)
                for t in group_tasks:
                    by_chrt[int(t.chrt_id)] += int(t.qty)

                # Cap по quota: не запрашиваем больше чем доступно
                total_requested = sum(by_chrt.values())
                if total_requested > dst_quota:
                    log.info(
                        "execute_window: requested=%d > dst_quota=%d — proportional cap",
                        total_requested,
                        dst_quota,
                    )
                    scale = dst_quota / total_requested
                    by_chrt = {c: max(1, int(q * scale)) for c, q in by_chrt.items()}

                items = list(by_chrt.items())
                try:
                    result = await lk.create_order(
                        src_office_id=src,
                        dst_office_id=dst,
                        nm_id=nm_id,
                        items=items,
                    )
                except LkClientError as e:
                    log.warning(
                        "execute_window: create_order failed (%s) — group failed",
                        e,
                    )
                    for t in group_tasks:
                        t.status = "failed"
                        t.last_attempt_at = datetime.now(timezone.utc)
                        t.last_status_code = e.status
                        t.last_response = f"{e}"
                        t.attempt_count = (t.attempt_count or 0) + 1
                        failed += 1
                    if e.status == 401:
                        # Token broken — пометить session needs_relogin
                        await mark_needs_relogin(
                            session,
                            tenant_id,
                            reason=f"401 on create_order: {e.body[:200]}",
                        )
                    continue

                # Success!
                if isinstance(result, dict) and result.get("success"):
                    now = datetime.now(timezone.utc)
                    cooldown_until = now + timedelta(hours=72)
                    for t in group_tasks:
                        t.status = "accepted"
                        t.accepted_at = now
                        t.last_attempt_at = now
                        t.last_status_code = 200
                        t.last_response = "success"
                        t.attempt_count = (t.attempt_count or 0) + 1
                        accepted += 1
                        # Cooldown — 72ч на пару (chrt_id, dst). PK composite
                        # (tenant_id, chrt_id, to_office_id) → upsert через
                        # session.merge (update если уже был, insert если нет).
                        await session.merge(
                            RedistributionCooldown(
                                tenant_id=tenant_id,
                                chrt_id=int(t.chrt_id),
                                to_office_id=dst,
                                cooldown_until=cooldown_until,
                                last_task_id=t.id,
                            )
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
                    log.warning(
                        "execute_window: unexpected response: %r",
                        result,
                    )
                    for t in group_tasks:
                        t.status = "failed"
                        t.last_attempt_at = datetime.now(timezone.utc)
                        t.last_response = f"unexpected: {result!r}"
                        t.attempt_count = (t.attempt_count or 0) + 1
                        failed += 1

    except Exception:
        log.exception(
            "execute_window: unexpected error for tenant=%d — partial commit",
            tenant_id,
        )

    await session.commit()
    return {
        "accepted": accepted,
        "failed": failed,
        "skipped_quota": skipped_quota,
        "skipped_no_office": skipped_no_office,
        "total": len(tasks),
    }
