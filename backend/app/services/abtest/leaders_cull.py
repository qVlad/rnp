"""Отсев лидеров через 24 ч после старта теста.

Запускается из rotation worker перед каждой проверкой ротации. Когда у теста:
    - status='running'
    - keep_leaders_after_24h=True
    - leaders_culled_at is NULL  (ещё не отсеивали)
    - started_at + 24ч <= now
    - вариантов > 2
→ берёт топ-2 по CTR (clicks/impressions, агрегат `abtest_daily_stat` без
  фильтра по source) и проставляет остальным `eliminated_at = now`. Дальнейшая
  ротация идёт только между двумя оставшимися.

Tie-break: при равных CTR — выигрывает вариант с большим числом показов;
при равных показах — алфавитный порядок label'а (A < B < C).
Все 0 показов → оставляем первые два по label.

Порт `wbab/src/lib/leaders-cull.ts` 1:1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AbTest,
    AbTestAlert,
    AbTestEvent,
    AbTestVariant,
)
from app.services.abtest.stats_queries import aggregate_variant_ctr

log = get_logger(__name__)

__all__ = ["run_leader_cull_for_test", "run_leader_cull_for_all"]

CULL_DELAY = timedelta(hours=24)


@dataclass
class _RankedVariant:
    id: int
    label: str
    impressions: int
    clicks: int
    ctr: float


def _rank(variants: list[_RankedVariant]) -> list[_RankedVariant]:
    """CTR↓, impressions↓, label↑."""
    return sorted(
        variants,
        key=lambda v: (-v.ctr, -v.impressions, v.label),
    )


async def run_leader_cull_for_test(
    session: AsyncSession,
    abtest_id: int,
) -> dict | None:
    """Возвращает `{"culled": N}` если отсев был выполнен, иначе None.

    Все условия проверяются внутри — caller (rotation) может вызвать неусловно
    перед каждой ротацией. Идемпотентно: `leaders_culled_at` запрещает повтор.
    """
    test = await session.get(AbTest, abtest_id)
    if test is None:
        return None
    if not test.keep_leaders_after_24h:
        return None
    if test.leaders_culled_at is not None:
        return None
    if test.status != "running":
        return None
    if test.started_at is None:
        return None

    now = datetime.now(timezone.utc)
    if now - test.started_at < CULL_DELAY:
        return None

    variants = (
        await session.execute(
            select(AbTestVariant)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestVariant.label)
        )
    ).scalars().all()
    if len(variants) <= 2:
        return None

    # Агрегат показов/кликов per-variant (sum по всем источникам и датам).
    agg = {vid: (imp, cl) for vid, imp, cl in await aggregate_variant_ctr(session, abtest_id)}

    ranked = [
        _RankedVariant(
            id=v.id,
            label=v.label,
            impressions=agg.get(v.id, (0, 0))[0],
            clicks=agg.get(v.id, (0, 0))[1],
            ctr=(agg.get(v.id, (0, 0))[1] / agg.get(v.id, (0, 0))[0])
            if agg.get(v.id, (0, 0))[0] > 0
            else 0.0,
        )
        for v in variants
    ]
    ranked = _rank(ranked)

    survivors = ranked[:2]
    eliminated = ranked[2:]
    if not eliminated:
        return None

    # Транзакционно: помечаем варианты eliminated, ставим test.leaders_culled_at,
    # пишем alert + events. SQLAlchemy AsyncSession уже в транзакции (auto-begin),
    # commit делает caller — `tenant_sync_context` через `task_session_scope`.
    await session.execute(
        update(AbTestVariant)
        .where(AbTestVariant.id.in_([e.id for e in eliminated]))
        .values(eliminated_at=now)
    )
    test.leaders_culled_at = now

    kept_str = ", ".join(f"{v.label} (CTR {v.ctr * 100:.2f}%)" for v in survivors)
    elim_str = ", ".join(f"{v.label} ({v.ctr * 100:.2f}%)" for v in eliminated)
    message = (
        f"Через 24 ч после старта оставлены 2 лидера по CTR: {kept_str}. "
        f"Отсеяны: {elim_str}."
    )
    session.add(
        AbTestAlert(
            tenant_id=test.tenant_id,
            abtest_id=abtest_id,
            message=message,
        )
    )

    kept_labels = [v.label for v in survivors]
    for e in eliminated:
        session.add(
            AbTestEvent(
                tenant_id=test.tenant_id,
                abtest_id=abtest_id,
                variant_id=e.id,
                kind="variant_eliminated",
                source="auto",
                event_metadata={
                    "variant_label": e.label,
                    "ctr": e.ctr,
                    "reason": "ctr-leader-cull",
                    "kept_labels": kept_labels,
                },
            )
        )

    await session.flush()  # видимо для caller'а в той же транзакции

    log.info(
        "[leaders-cull] test %d: kept [%s], eliminated [%s]",
        abtest_id,
        ",".join(str(v.id) for v in survivors),
        ",".join(str(v.id) for v in eliminated),
    )
    return {"culled": len(eliminated)}


async def run_leader_cull_for_all(session: AsyncSession) -> int:
    """Прогонит отсев по всем подходящим running-тестам.

    Не используется в rotation (там cull для конкретного теста вызывается
    перед его ротацией). Оставлен для админ-команд и будущего beat-task'а.
    """
    cutoff = datetime.now(timezone.utc) - CULL_DELAY
    ids = (
        await session.execute(
            select(AbTest.id).where(
                AbTest.status == "running",
                AbTest.keep_leaders_after_24h.is_(True),
                AbTest.leaders_culled_at.is_(None),
                AbTest.started_at <= cutoff,
            )
        )
    ).scalars().all()

    total = 0
    for tid in ids:
        r = await run_leader_cull_for_test(session, tid)
        if r:
            total += r["culled"]
    return total
