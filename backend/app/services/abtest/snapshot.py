"""Snapshot-diff атрибуция показов A/B-тестов к активному варианту.

Проблема: WB API отдаёт только дневные кумулятивы. При TIME=30мин фото
меняется до 48 раз в день. Записать «весь день» к одному варианту нельзя.

Решение: данные WB обновляются ≈ раз в час и являются кумулятивными за день.
Делаем частые snapshot'ы → дельта между ними → атрибутируем к варианту,
активному в интервале `(prev.captured_at, now]`. Эффективная гранулярность
≈ 1 час (по cadence обновления WB).

Поведение на границах:
- Первый snapshot для дня — baseline (всё что было до старта теста уходит
  сюда без атрибуции).
- При переходе календарного дня (Moscow TZ) — снова baseline.
- При ротации внутри интервала: дельта делится между вариантами по доле
  времени, в течение которого каждый был активен.

Порт `wbab/src/lib/stats/snapshot.ts` + `platform-snapshot.ts` (последний
тот же алгоритм с лишней размерностью «платформа»).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AbTestAdPlatformSnapshot,
    AbTestAdPlatformStat,
    AbTestDailyStat,
    AbTestStatsSnapshot,
)

log = get_logger(__name__)

__all__ = [
    "SnapshotInput",
    "PlatformSnapshotInput",
    "Rotation",
    "VariantRef",
    "apply_snapshot",
    "apply_platform_snapshot",
    "clear_snapshots_for_test",
    "moscow_date_str",
    "day_key",
]


MOSCOW = ZoneInfo("Europe/Moscow")


def moscow_date_str(dt: datetime) -> str:
    """YYYY-MM-DD по Москве для UTC-момента (соответствует группировке WB)."""
    return dt.astimezone(MOSCOW).strftime("%Y-%m-%d")


def day_key(date_str: str) -> date:
    """ISO YYYY-MM-DD → `date` для колонки `day_date` (тип Date)."""
    return date.fromisoformat(date_str[:10])


@dataclass
class VariantRef:
    id: int
    label: str


@dataclass
class Rotation:
    variant_id: int
    applied_at: datetime


@dataclass
class SnapshotInput:
    abtest_id: int
    tenant_id: int
    source: str  # "adv" | "nm-report"
    captured_at: datetime
    cum_impressions: int
    cum_clicks: int
    cum_cart_adds: int
    cum_orders: int
    cum_ad_spend: float
    cum_revenue: float


@dataclass
class PlatformSnapshotInput:
    abtest_id: int
    tenant_id: int
    captured_at: datetime
    platform: str  # "IOS" | "ANDROID" | "WEB" | "OTHER"
    cum_impressions: int
    cum_clicks: int
    cum_orders: int
    cum_ad_spend: float


@dataclass
class SnapshotResult:
    delta_impressions: int
    baseline: bool
    reason: str | None = None


def _attribute_interval_to_variants(
    from_dt: datetime,
    to_dt: datetime,
    variants: list[VariantRef],
    rotations: list[Rotation],
) -> dict[int, float]:
    """Делит интервал [from, to) между вариантами по доле фактической активности.

    Возвращает map variant_id → доля (sum = 1.0 при наличии активности).
    Пустой dict если интервал нулевой или нет вариантов.
    """
    total_s = (to_dt - from_dt).total_seconds()
    if total_s <= 0 or not variants:
        return {}

    # Все ротации, успешные и применённые до 'to', отсортированные по времени.
    sorted_rot = sorted(
        (r for r in rotations if r.applied_at < to_dt),
        key=lambda r: r.applied_at,
    )

    # «Текущий вариант на момент 'from'» — последняя ротация ≤ from, иначе первый вариант.
    before_from = [r for r in sorted_rot if r.applied_at <= from_dt]
    if before_from:
        current_id = before_from[-1].variant_id
    else:
        current_id = variants[0].id

    # Ротации, попадающие внутрь (from, to).
    inside = [r for r in sorted_rot if from_dt < r.applied_at < to_dt]

    result: dict[int, float] = {}
    cursor = from_dt
    for rot in inside:
        seg_s = (rot.applied_at - cursor).total_seconds()
        if seg_s > 0:
            result[current_id] = result.get(current_id, 0.0) + seg_s
        current_id = rot.variant_id
        cursor = rot.applied_at
    # Финальный сегмент.
    tail_s = (to_dt - cursor).total_seconds()
    if tail_s > 0:
        result[current_id] = result.get(current_id, 0.0) + tail_s

    # Превращаем секунды в доли.
    return {k: v / total_s for k, v in result.items()}


async def _previous_snapshot(
    session: AsyncSession,
    abtest_id: int,
    source: str,
    day: date,
) -> AbTestStatsSnapshot | None:
    return (
        await session.execute(
            select(AbTestStatsSnapshot)
            .where(
                AbTestStatsSnapshot.abtest_id == abtest_id,
                AbTestStatsSnapshot.source == source,
                AbTestStatsSnapshot.day_date == day,
            )
            .order_by(AbTestStatsSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _previous_platform_snapshot(
    session: AsyncSession,
    abtest_id: int,
    platform: str,
    day: date,
) -> AbTestAdPlatformSnapshot | None:
    return (
        await session.execute(
            select(AbTestAdPlatformSnapshot)
            .where(
                AbTestAdPlatformSnapshot.abtest_id == abtest_id,
                AbTestAdPlatformSnapshot.platform == platform,
                AbTestAdPlatformSnapshot.day_date == day,
            )
            .order_by(AbTestAdPlatformSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _get_daily_stat(
    session: AsyncSession,
    variant_id: int,
    stat_date: date,
    source: str,
) -> AbTestDailyStat | None:
    return (
        await session.execute(
            select(AbTestDailyStat).where(
                AbTestDailyStat.variant_id == variant_id,
                AbTestDailyStat.stat_date == stat_date,
                AbTestDailyStat.source == source,
            )
        )
    ).scalar_one_or_none()


async def _get_platform_stat(
    session: AsyncSession,
    variant_id: int,
    stat_date: date,
    platform: str,
) -> AbTestAdPlatformStat | None:
    return (
        await session.execute(
            select(AbTestAdPlatformStat).where(
                AbTestAdPlatformStat.variant_id == variant_id,
                AbTestAdPlatformStat.stat_date == stat_date,
                AbTestAdPlatformStat.platform == platform,
            )
        )
    ).scalar_one_or_none()


async def apply_snapshot(
    session: AsyncSession,
    inp: SnapshotInput,
    variants: list[VariantRef],
    rotations: list[Rotation],
) -> SnapshotResult:
    """Применить новый snapshot: инкрементить `abtest_daily_stat` дельтой.

    Caller отвечает за commit транзакции (мы только `session.add`/`session.flush`).
    """
    day_str = moscow_date_str(inp.captured_at)
    day = day_key(day_str)

    prev = await _previous_snapshot(session, inp.abtest_id, inp.source, day)

    def _write_snapshot() -> None:
        session.add(
            AbTestStatsSnapshot(
                tenant_id=inp.tenant_id,
                abtest_id=inp.abtest_id,
                source=inp.source,
                day_date=day,
                captured_at=inp.captured_at,
                cum_impressions=inp.cum_impressions,
                cum_clicks=inp.cum_clicks,
                cum_cart_adds=inp.cum_cart_adds,
                cum_orders=inp.cum_orders,
                cum_ad_spend=Decimal(str(inp.cum_ad_spend)),
                cum_revenue=Decimal(str(inp.cum_revenue)),
            )
        )

    if prev is None:
        # Первый snapshot за день — baseline, дельту не атрибутируем.
        _write_snapshot()
        await session.flush()
        return SnapshotResult(0, baseline=True, reason="first snapshot of day")

    d_imp = max(0, inp.cum_impressions - prev.cum_impressions)
    d_clicks = max(0, inp.cum_clicks - prev.cum_clicks)
    d_cart = max(0, inp.cum_cart_adds - prev.cum_cart_adds)
    d_orders = max(0, inp.cum_orders - prev.cum_orders)
    d_ad_spend = max(0.0, float(inp.cum_ad_spend) - float(prev.cum_ad_spend))
    d_revenue = max(0.0, float(inp.cum_revenue) - float(prev.cum_revenue))

    if d_imp == 0 and d_clicks == 0 and d_cart == 0 and d_orders == 0:
        _write_snapshot()
        await session.flush()
        return SnapshotResult(0, baseline=False, reason="no change")

    shares = _attribute_interval_to_variants(
        prev.captured_at, inp.captured_at, variants, rotations
    )
    if not shares:
        # В интервале не было активного варианта (нет ротаций до 'to') —
        # фолбэк: всё на первый.
        shares = {variants[0].id: 1.0}

    for variant_id, share in shares.items():
        add_imp = round(d_imp * share)
        add_clicks = round(d_clicks * share)
        add_cart = round(d_cart * share)
        add_orders = round(d_orders * share)
        add_ad_spend = d_ad_spend * share
        add_revenue = d_revenue * share

        if (
            add_imp == 0 and add_clicks == 0 and add_cart == 0
            and add_orders == 0 and add_ad_spend == 0.0
        ):
            continue

        existing = await _get_daily_stat(session, variant_id, day, inp.source)
        if existing is not None:
            new_imp = existing.impressions + add_imp
            new_clicks = existing.clicks + add_clicks
            new_orders = existing.orders + add_orders
            existing.impressions = new_imp
            existing.clicks = new_clicks
            existing.cart_adds = existing.cart_adds + add_cart
            existing.orders = new_orders
            existing.ad_spend = existing.ad_spend + Decimal(str(add_ad_spend))
            existing.revenue = existing.revenue + Decimal(str(add_revenue))
            existing.ctr = Decimal(str(new_clicks / new_imp)) if new_imp > 0 else Decimal(0)
            existing.cr = (
                Decimal(str(new_orders / new_clicks))
                if new_clicks > 0
                else Decimal(0)
            )
        else:
            session.add(
                AbTestDailyStat(
                    tenant_id=inp.tenant_id,
                    variant_id=variant_id,
                    stat_date=day,
                    source=inp.source,
                    impressions=add_imp,
                    clicks=add_clicks,
                    cart_adds=add_cart,
                    orders=add_orders,
                    ad_spend=Decimal(str(add_ad_spend)),
                    revenue=Decimal(str(add_revenue)),
                    ctr=Decimal(str(add_clicks / add_imp)) if add_imp > 0 else Decimal(0),
                    cr=Decimal(str(add_orders / add_clicks)) if add_clicks > 0 else Decimal(0),
                )
            )

    _write_snapshot()
    await session.flush()
    return SnapshotResult(d_imp, baseline=False)


async def apply_platform_snapshot(
    session: AsyncSession,
    inp: PlatformSnapshotInput,
    variants: list[VariantRef],
    rotations: list[Rotation],
) -> SnapshotResult:
    """Та же логика, но с per-platform размерностью (IOS/ANDROID/WEB/OTHER).

    Пишет в `abtest_ad_platform_stat` + `abtest_ad_platform_snapshot`.
    """
    day_str = moscow_date_str(inp.captured_at)
    day = day_key(day_str)

    prev = await _previous_platform_snapshot(session, inp.abtest_id, inp.platform, day)

    def _write_snapshot() -> None:
        session.add(
            AbTestAdPlatformSnapshot(
                tenant_id=inp.tenant_id,
                abtest_id=inp.abtest_id,
                day_date=day,
                platform=inp.platform,
                captured_at=inp.captured_at,
                cum_impressions=inp.cum_impressions,
                cum_clicks=inp.cum_clicks,
                cum_orders=inp.cum_orders,
                cum_ad_spend=Decimal(str(inp.cum_ad_spend)),
            )
        )

    if prev is None:
        _write_snapshot()
        await session.flush()
        return SnapshotResult(0, baseline=True, reason="first platform snapshot of day")

    d_imp = max(0, inp.cum_impressions - prev.cum_impressions)
    d_clicks = max(0, inp.cum_clicks - prev.cum_clicks)
    d_orders = max(0, inp.cum_orders - prev.cum_orders)
    d_ad_spend = max(0.0, float(inp.cum_ad_spend) - float(prev.cum_ad_spend))

    if d_imp == 0 and d_clicks == 0 and d_orders == 0 and d_ad_spend == 0.0:
        _write_snapshot()
        await session.flush()
        return SnapshotResult(0, baseline=False, reason="no change")

    shares = _attribute_interval_to_variants(
        prev.captured_at, inp.captured_at, variants, rotations
    )
    if not shares:
        shares = {variants[0].id: 1.0}

    for variant_id, share in shares.items():
        add_imp = round(d_imp * share)
        add_clicks = round(d_clicks * share)
        add_orders = round(d_orders * share)
        add_ad_spend = d_ad_spend * share

        if add_imp == 0 and add_clicks == 0 and add_orders == 0 and add_ad_spend == 0.0:
            continue

        existing = await _get_platform_stat(session, variant_id, day, inp.platform)
        if existing is not None:
            existing.impressions = existing.impressions + add_imp
            existing.clicks = existing.clicks + add_clicks
            existing.orders = existing.orders + add_orders
            existing.ad_spend = existing.ad_spend + Decimal(str(add_ad_spend))
        else:
            session.add(
                AbTestAdPlatformStat(
                    tenant_id=inp.tenant_id,
                    variant_id=variant_id,
                    stat_date=day,
                    platform=inp.platform,
                    impressions=add_imp,
                    clicks=add_clicks,
                    orders=add_orders,
                    ad_spend=Decimal(str(add_ad_spend)),
                )
            )

    _write_snapshot()
    await session.flush()
    return SnapshotResult(d_imp, baseline=False)


async def clear_snapshots_for_test(session: AsyncSession, abtest_id: int) -> None:
    """Удалить все snapshot'ы теста — используется при перезапуске."""
    await session.execute(
        delete(AbTestStatsSnapshot).where(AbTestStatsSnapshot.abtest_id == abtest_id)
    )
    await session.execute(
        delete(AbTestAdPlatformSnapshot).where(
            AbTestAdPlatformSnapshot.abtest_id == abtest_id
        )
    )
    await session.flush()


# Внутренние хелперы экспортируем для тестов.
__test_only__ = {
    "_attribute_interval_to_variants": _attribute_interval_to_variants,
    "moscow_date_str": moscow_date_str,
    "day_key": day_key,
}
