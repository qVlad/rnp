"""Read-only helpers для A/B-статистики.

В этой фазе (3b-i) — минимум, нужный rotation/leaders_cull: подсчитать
показы варианта с момента last rotation, агрегаты CTR per-variant.

Полная sync-логика (заполнение abtest_daily_stat / abtest_stats_snapshot
из nm-report + adv) — phase 3b-ii в `stats.py`. До неё статистика будет
пустая → VIEWS-триггер ротации никогда не сработает (rotation полагается
на TIME-триггер пока stats.py не подключён).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AbTestDailyStat, AbTestStatsSnapshot, AbTestVariant

__all__ = [
    "get_impressions_for_variant_since",
    "aggregate_variant_ctr",
    "latest_adv_snapshot_at_or_before",
    "latest_adv_snapshot",
]


async def get_impressions_for_variant_since(
    session: AsyncSession,
    variant_id: int,
    since: datetime,
    source_filter: str | None = None,
) -> int:
    """Суммарно показов варианта с момента `since` (включительно).

    `source_filter`:
      - None — все источники (`nm-report` + `adv`)
      - 'adv' — только adv (для BOTH-тестов: nm-report.openCount уже включает
        adv-клики, без фильтра было бы дабл-каунт adv-показов → триггер
        срабатывал бы в ~2 раза раньше).
      - 'nm-report' — только nm-report.

    Сравнение даты `stat_date >= since.date()` — у нас day-resolution
    в `abtest_daily_stat`, точнее не получится без snapshot-diff.
    """
    stmt = (
        select(func.coalesce(func.sum(AbTestDailyStat.impressions), 0))
        .where(
            AbTestDailyStat.variant_id == variant_id,
            AbTestDailyStat.stat_date >= since.date(),
        )
    )
    if source_filter is not None:
        stmt = stmt.where(AbTestDailyStat.source == source_filter)
    val = await session.scalar(stmt)
    return int(val or 0)


async def aggregate_variant_ctr(
    session: AsyncSession,
    abtest_id: int,
) -> list[tuple[int, int, int]]:
    """Возвращает агрегат `(variant_id, sum_impressions, sum_clicks)` по тесту.

    Без фильтра по source (как в wbab leaders-cull.ts) — суммируем nm-report +
    adv. Для leader cull важен абсолютный CTR, а не атрибуция.
    """
    variant_ids_subq = (
        select(AbTestVariant.id).where(AbTestVariant.abtest_id == abtest_id)
    )
    stmt = (
        select(
            AbTestDailyStat.variant_id,
            func.coalesce(func.sum(AbTestDailyStat.impressions), 0),
            func.coalesce(func.sum(AbTestDailyStat.clicks), 0),
        )
        .where(AbTestDailyStat.variant_id.in_(variant_ids_subq))
        .group_by(AbTestDailyStat.variant_id)
    )
    rows = (await session.execute(stmt)).all()
    return [(int(r[0]), int(r[1]), int(r[2])) for r in rows]


async def latest_adv_snapshot_at_or_before(
    session: AsyncSession,
    abtest_id: int,
    moment: datetime,
) -> AbTestStatsSnapshot | None:
    """Snapshot adv-кумулятивов с `captured_at <= moment`, последний по времени.

    Используется в BUDGET-триггере: baseline для дельты spent с момента
    last rotation. Snapshot снимается ПЕРЕД ротацией → snapshot с captured_at
    близко к `last_rotation.applied_at` — нужная «точка отсчёта».
    """
    stmt = (
        select(AbTestStatsSnapshot)
        .where(
            AbTestStatsSnapshot.abtest_id == abtest_id,
            AbTestStatsSnapshot.source == "adv",
            AbTestStatsSnapshot.captured_at <= moment,
        )
        .order_by(AbTestStatsSnapshot.captured_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def latest_adv_snapshot(
    session: AsyncSession,
    abtest_id: int,
) -> AbTestStatsSnapshot | None:
    """Последний adv-snapshot теста (самый свежий)."""
    stmt = (
        select(AbTestStatsSnapshot)
        .where(
            AbTestStatsSnapshot.abtest_id == abtest_id,
            AbTestStatsSnapshot.source == "adv",
        )
        .order_by(AbTestStatsSnapshot.captured_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
