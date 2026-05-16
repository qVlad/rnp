"""Sync статистики A/B-тестов из WB API.

Порт `wbab/src/lib/stats.ts` (без buyout-sync — это CSV-task через WB Jam,
deferred к Phase 6+; и без `compute_platform_report` — UI-only, тоже потом).

Точки входа:
- `sync_test_stats(session, test, wb, quick_sync=False)` — один тест, использует
  уже открытые session+wb (вызывается из rotation.py перед ротацией).
- `sync_running_tests_for_tenant(tenant_id, quick_sync=False)` — все running
  тесты одного tenant'а (вызывается из Celery beat task per tenant).
- `get_daily_stats_by_test(session, abtest_id)` — read для UI/API.

Источники данных (определяются `test.traffic_source`):
- ANY      → только nm-report (общий трафик карточки)
- ADV_ONLY → только adv (трафик из рекламной кампании)
- BOTH     → оба параллельно

`quick_sync=True` (вызывается из rotation hot-path): пропускает adv API,
синкается только nm-report. Adv лимиты строгие (3/min с min_interval 20s)
и rotation worker идёт каждые 15 мин — постоянный adv sync съест cooldown.
Полный sync — раз в 6 ч по расписанию (Phase 5).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AbTest,
    AbTestRotation,
    AbTestVariant,
)
from app.integrations.wb import advert as wb_advert
from app.integrations.wb import analytics as wb_analytics
from app.integrations.wb.client import WbApiClient, WbApiError
from app.services.abtest.platforms import app_type_to_platform
from app.services.abtest.snapshot import (
    PlatformSnapshotInput,
    Rotation,
    SnapshotInput,
    VariantRef,
    apply_platform_snapshot,
    apply_snapshot,
    moscow_date_str,
)
from app.sync.tenants import tenant_sync_context

log = get_logger(__name__)

__all__ = [
    "sync_test_stats",
    "sync_running_tests_for_tenant",
    "get_daily_stats_by_test",
]

# WB отдаёт максимум 30-31 день истории в nm-report / adv v3 fullstats.
HISTORY_DAYS = 30


# ----------------------------------------------------------------------
# Public entries
# ----------------------------------------------------------------------


async def sync_test_stats(
    session: AsyncSession,
    test: AbTest,
    wb: WbApiClient,
    *,
    quick_sync: bool = False,
) -> None:
    """Синк статистики одного теста. Caller предоставляет открытые session+wb.

    Источники: ANY → nm-report; ADV_ONLY → adv (если не quick_sync);
    BOTH → оба. `Promise.allSettled` поведение — частичная ошибка одного
    источника не валит другой (для BOTH).
    """
    if test.status != "running":
        return

    variants = await _load_variants(session, test.id)
    rotations = await _load_rotations(session, test.id)

    want_adv = (
        not quick_sync
        and test.campaign_id is not None
        and test.traffic_source in ("ADV_ONLY", "BOTH")
    )
    want_nm = test.traffic_source in ("ANY", "BOTH")

    if want_adv:
        try:
            await _sync_adv_stats(session, test, wb, variants, rotations)
        except Exception as e:
            # Для BOTH повторный fallback в nm-report НЕ делаем — он уже
            # синкается параллельно ниже. Для ADV_ONLY оставляем fallback.
            if test.traffic_source == "BOTH":
                log.warning(
                    "[stats] adv sync failed for BOTH test %d campaign %s: %s "
                    "(nm-report syncs in parallel)",
                    test.id, test.campaign_id, e,
                )
            else:
                log.warning(
                    "[stats] ADV_ONLY adv sync failed for test %d campaign %s: %s "
                    "— falling back to nm-report",
                    test.id, test.campaign_id, e,
                )
                try:
                    await _sync_nm_report_stats(session, test, wb, variants, rotations)
                except Exception as e2:
                    log.warning("[stats] nm-report fallback failed: %s", e2)
                return

    if want_nm:
        try:
            await _sync_nm_report_stats(session, test, wb, variants, rotations)
        except Exception as e:
            log.warning("[stats] nm-report sync failed for test %d: %s", test.id, e)

    # Auto-topup check — каждый раз когда мы и так общаемся с WB по тесту.
    # Дубликат с poll_all_budgets_for_tenant исключён через дневной счётчик.
    # Только при full sync (quick_sync=False) — иначе rotation hot-path
    # делал бы лишний GET /adv/v1/budget каждые 15 мин.
    if not quick_sync:
        from app.services.abtest.budget import maybe_topup_budget
        try:
            await maybe_topup_budget(session, test, wb)
        except Exception as e:
            log.warning("[stats] budget topup check failed for test %d: %s", test.id, e)


async def sync_running_tests_for_tenant(
    tenant_id: int, *, quick_sync: bool = False
) -> int:
    """Все running-тесты tenant'а. Возвращает число успешно синканных."""
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("[stats] tenant %d no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        tests = (
            await session.execute(
                select(AbTest).where(
                    AbTest.tenant_id == tenant_id,
                    AbTest.status == "running",
                )
            )
        ).scalars().all()
        if not tests:
            return 0
        ok_count = 0
        for test in tests:
            try:
                await sync_test_stats(session, test, wb, quick_sync=quick_sync)
                ok_count += 1
            except Exception as e:
                log.exception(
                    "[stats] error syncing test %d in tenant %d: %s",
                    test.id, tenant_id, e,
                )
        return ok_count


async def get_daily_stats_by_test(
    session: AsyncSession, abtest_id: int
) -> list[dict]:
    """Дневные данные для графика/расчёта значимости в UI.

    Каждая строка: variant_id, variant_label, stat_date, impressions, clicks,
    orders, ctr, cr, source. Joined с variant ради label'а.
    """
    from app.db.models import AbTestDailyStat  # local import — avoid cycle с snapshot.py

    rows = (
        await session.execute(
            select(
                AbTestDailyStat.variant_id,
                AbTestVariant.label,
                AbTestDailyStat.stat_date,
                AbTestDailyStat.impressions,
                AbTestDailyStat.clicks,
                AbTestDailyStat.orders,
                AbTestDailyStat.ctr,
                AbTestDailyStat.cr,
                AbTestDailyStat.source,
            )
            .join(AbTestVariant, AbTestVariant.id == AbTestDailyStat.variant_id)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestDailyStat.stat_date)
        )
    ).all()
    return [
        {
            "variant_id": r[0],
            "variant_label": r[1],
            "stat_date": r[2],
            "impressions": r[3],
            "clicks": r[4],
            "orders": r[5],
            "ctr": float(r[6] or 0),
            "cr": float(r[7] or 0),
            "source": r[8],
        }
        for r in rows
    ]


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


async def _load_variants(
    session: AsyncSession, abtest_id: int
) -> list[VariantRef]:
    rows = (
        await session.execute(
            select(AbTestVariant.id, AbTestVariant.label)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestVariant.label)
        )
    ).all()
    return [VariantRef(id=int(r[0]), label=str(r[1])) for r in rows]


async def _load_rotations(
    session: AsyncSession, abtest_id: int
) -> list[Rotation]:
    rows = (
        await session.execute(
            select(AbTestRotation.variant_id, AbTestRotation.applied_at)
            .where(
                AbTestRotation.abtest_id == abtest_id,
                AbTestRotation.success.is_(True),
            )
            .order_by(AbTestRotation.applied_at)
        )
    ).all()
    return [Rotation(variant_id=int(r[0]), applied_at=r[1]) for r in rows]


def _period_start(started_at: datetime | None, days_back: int = HISTORY_DAYS) -> datetime:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    if started_at is not None and started_at > cutoff:
        return started_at
    return cutoff


# ---------- nm-report ----------


async def _sync_nm_report_stats(
    session: AsyncSession,
    test: AbTest,
    wb: WbApiClient,
    variants: list[VariantRef],
    rotations: list[Rotation],
) -> None:
    today = datetime.now(timezone.utc)
    period_start = _period_start(test.started_at)

    cards = await wb_analytics.fetch_nm_report_history(
        wb,
        nm_ids=[test.nm_id],
        date_from=period_start.date(),
        date_to=today.date(),
        aggregation_level="day",
    )
    if not cards:
        return

    # API формат: [{"product": {"nmId": ...}, "history": [{...}, ...]}, ...]
    # либо плоский [{"nmID": ..., "history": ...}, ...] (зависит от WB-версии).
    nm_id = int(test.nm_id)
    card = None
    for c in cards:
        prod = c.get("product") or {}
        cand = prod.get("nmId") or prod.get("nmID") or c.get("nmID") or c.get("nmId")
        if int(cand or 0) == nm_id:
            card = c
            break
    if not card:
        return
    history = card.get("history") or []
    if not history:
        return

    today_moscow = moscow_date_str(today)
    today_day = next(
        (d for d in history if str(d.get("dt") or d.get("date") or "")[:10] == today_moscow),
        None,
    )
    if today_day is None:
        return  # ещё нет данных за сегодня

    if test.started_at is not None:
        started_moscow = moscow_date_str(test.started_at)
        if today_moscow < started_moscow:
            return  # запас на race condition

    # nm-report-поля: openCardCount = открытия (impressions),
    # addToCartCount = клики (~ интерес), orderCount = заказы,
    # ordersSumRub = выручка. WB v3 имена могут варьироваться.
    cum_imp = int(today_day.get("openCardCount") or today_day.get("openCount") or 0)
    cum_clicks = int(today_day.get("addToCartCount") or today_day.get("cartCount") or 0)
    cum_orders = int(today_day.get("ordersCount") or today_day.get("orderCount") or 0)
    cum_revenue = float(today_day.get("ordersSumRub") or today_day.get("orderSum") or 0)

    await apply_snapshot(
        session,
        SnapshotInput(
            abtest_id=test.id,
            tenant_id=test.tenant_id,
            source="nm-report",
            captured_at=today,
            cum_impressions=cum_imp,
            # Для nm-report «клик» = добавление в корзину (WB не отдаёт отдельный клик).
            cum_clicks=cum_clicks,
            cum_cart_adds=cum_clicks,
            cum_orders=cum_orders,
            cum_ad_spend=0.0,
            cum_revenue=cum_revenue,
        ),
        variants,
        rotations,
    )


# ---------- adv ----------


async def _sync_adv_stats(
    session: AsyncSession,
    test: AbTest,
    wb: WbApiClient,
    variants: list[VariantRef],
    rotations: list[Rotation],
) -> None:
    if test.campaign_id is None:
        return

    today = datetime.now(timezone.utc)
    period_start = _period_start(test.started_at)

    try:
        items = await wb_advert.fetch_fullstats(
            wb,
            advert_ids=[int(test.campaign_id)],
            date_from=period_start.date(),
            date_to=today.date(),
        )
    except WbApiError as e:
        raise  # caller обработает (BOTH/ADV_ONLY ветка в sync_test_stats)

    if not items:
        return

    # WB может вернуть массив с одним элементом, либо объект напрямую (один advertId).
    item = None
    for it in items:
        if int(it.get("advertId") or 0) == int(test.campaign_id):
            item = it
            break
    if item is None:
        return

    days = item.get("days") or []
    today_moscow = moscow_date_str(today)
    today_day = next(
        (d for d in days if str(d.get("date") or "")[:10] == today_moscow),
        None,
    )
    if today_day is None:
        # Иногда WB возвращает только агрегат — это означает «нет дневных данных
        # за период»; нечего атрибутировать.
        return

    if test.started_at is not None:
        started_moscow = moscow_date_str(test.started_at)
        if today_moscow < started_moscow:
            return

    cum_views = int(today_day.get("views") or 0)
    cum_clicks = int(today_day.get("clicks") or 0)
    cum_atbs = int(today_day.get("atbs") or 0)  # add-to-basket
    cum_orders = int(today_day.get("orders") or 0)
    cum_ad_spend = float(today_day.get("sum") or 0)
    cum_revenue = float(today_day.get("sum_price") or 0)

    await apply_snapshot(
        session,
        SnapshotInput(
            abtest_id=test.id,
            tenant_id=test.tenant_id,
            source="adv",
            captured_at=today,
            cum_impressions=cum_views,
            cum_clicks=cum_clicks,
            cum_cart_adds=cum_atbs,
            cum_orders=cum_orders,
            cum_ad_spend=cum_ad_spend,
            cum_revenue=cum_revenue,
        ),
        variants,
        rotations,
    )

    # Per-platform: aggregate `apps[]` per platform (несколько appType могут
    # маппиться на одну платформу — суммируем).
    platform_agg: dict[str, dict[str, float]] = {}
    for a in today_day.get("apps") or []:
        platform = app_type_to_platform(int(a.get("appType") or 0))
        cur = platform_agg.setdefault(
            platform, {"views": 0, "clicks": 0, "orders": 0, "sum": 0.0}
        )
        cur["views"] += int(a.get("views") or 0)
        cur["clicks"] += int(a.get("clicks") or 0)
        cur["orders"] += int(a.get("orders") or 0)
        cur["sum"] += float(a.get("sum") or 0)

    for platform, agg in platform_agg.items():
        if agg["views"] == 0 and agg["clicks"] == 0:
            continue
        await apply_platform_snapshot(
            session,
            PlatformSnapshotInput(
                abtest_id=test.id,
                tenant_id=test.tenant_id,
                captured_at=today,
                platform=platform,
                cum_impressions=int(agg["views"]),
                cum_clicks=int(agg["clicks"]),
                cum_orders=int(agg["orders"]),
                cum_ad_spend=agg["sum"],
            ),
            variants,
            rotations,
        )
