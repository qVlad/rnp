"""Ротация фото-вариантов A/B-теста по триггеру.

Порт `wbab/src/lib/rotation.ts` на Python/SQLAlchemy. Сохраняет ту же
семантику триггеров (VIEWS / TIME / BUDGET) и тот же контракт записей
в `abtest_rotation` (1 запись на ротацию, success=True только когда все
фото варианта успешно загружены).

Точки входа:
- `check_and_rotate_all(session)`         — пробег по всем running-тестам
                                              (вызывается Celery beat-task'ом).
- `check_and_rotate_for_test(session, id)` — per-test (self-scheduled job'ы).
- `apply_initial_variant(session, id)`     — старт теста: грузим вариант A.
- `apply_winner_variant(session, id, vid)` — финализация: грузим победителя
                                              и переводим тест в completed.

Зависимости:
- WbApiClient + content_media.upload_media_file — Phase 2 (готовы)
- photo_storage.read_variant_photo            — Phase 3a (готов)
- stats_queries.get_impressions_for_variant_since — Phase 3b-i (новый)
- leaders_cull.run_leader_cull_for_test       — Phase 3b-i (новый)
- Self-scheduling (`_schedule_test_rotation_check`) — stub до Phase 5
  (когда подключим Celery task). Пока полагаемся на beat cadence (15 мин).
- `sync_stats_for_tests([test.id])` — Phase 3b-ii (не порт ещё); пока
  no-op с предупреждением в лог. BUDGET-триггер будет работать только
  после Phase 3b-ii (нет snapshot'ов = нет дельты spent).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AbTest,
    AbTestRotation,
    AbTestVariant,
    AbTestVariantPhoto,
    Product,
)
from app.integrations.wb import content_media
from app.integrations.wb.client import WbApiClient, WbApiError
from app.services.abtest import photo_storage
from app.services.abtest.leaders_cull import run_leader_cull_for_test
from app.services.abtest.stats_queries import (
    get_impressions_for_variant_since,
    latest_adv_snapshot,
    latest_adv_snapshot_at_or_before,
)
from app.sync.tenants import wb_client_for_tenant

log = get_logger(__name__)

__all__ = [
    "check_and_rotate_all",
    "check_and_rotate_for_test",
    "apply_initial_variant",
    "apply_winner_variant",
]

# Пауза между загрузкой фото одного варианта — WB Content media лимит ~10/мин.
# 7 секунд = ~8.5 req/min < 10. Безопасный потолок.
PHOTO_UPLOAD_PAUSE_S = 7.0


# ----------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------


async def check_and_rotate_all(session: AsyncSession) -> int:
    """Прогон по всем running-тестам. Возвращает число выполненных ротаций.

    Один `WbApiClient` per tenant: тесты группируются по `tenant_id`,
    клиент открывается один раз для всего набора тестов tenant'а.
    """
    tests = (
        await session.execute(
            select(AbTest).where(AbTest.status == "running")
        )
    ).scalars().all()
    if not tests:
        return 0

    # Группируем по tenant_id чтобы открыть один клиент per tenant.
    by_tenant: dict[int, list[AbTest]] = {}
    for t in tests:
        by_tenant.setdefault(t.tenant_id, []).append(t)

    rotated_count = 0
    for tenant_id, tenant_tests in by_tenant.items():
        try:
            client = await wb_client_for_tenant(session, tenant_id)
        except RuntimeError:
            log.info(
                "[rotation] tenant %d has no WB token, skip %d tests",
                tenant_id, len(tenant_tests),
            )
            continue
        async with client as wb:
            for test in tenant_tests:
                try:
                    if await run_leader_cull_for_test(session, test.id) is not None:
                        # leaders_cull сам commit'нет через caller'а;
                        # но мы хотим, чтобы test.refresh подхватил leaders_culled_at
                        await session.refresh(test)
                except Exception as e:
                    log.exception(
                        "[rotation] leader-cull failed for test %d: %s", test.id, e
                    )
                try:
                    if await _check_and_rotate_one(session, test, wb):
                        rotated_count += 1
                except Exception as e:
                    log.exception("[rotation] error processing test %d: %s", test.id, e)
    return rotated_count


async def check_and_rotate_for_test(
    session: AsyncSession, abtest_id: int
) -> bool:
    """Per-test ротация — для self-scheduled job'ов (Phase 5)."""
    test = await session.get(AbTest, abtest_id)
    if test is None or test.status != "running":
        return False
    try:
        await run_leader_cull_for_test(session, abtest_id)
        await session.refresh(test)
    except Exception as e:
        log.exception("[rotation] leader-cull failed for test %d: %s", abtest_id, e)
    try:
        client = await wb_client_for_tenant(session, test.tenant_id)
    except RuntimeError:
        log.info("[rotation] tenant %d no WB token", test.tenant_id)
        return False
    async with client as wb:
        return await _check_and_rotate_one(session, test, wb)


async def apply_initial_variant(
    session: AsyncSession, abtest_id: int
) -> bool:
    """Старт теста — заливаем вариант A на WB."""
    test = await session.get(AbTest, abtest_id)
    if test is None:
        return False
    first_variant = (
        await session.execute(
            select(AbTestVariant)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestVariant.label)
            .limit(1)
        )
    ).scalar_one_or_none()
    if first_variant is None:
        return False
    nm_id = await _nm_id_for_test(session, test)
    if nm_id is None:
        return False
    try:
        client = await wb_client_for_tenant(session, test.tenant_id)
    except RuntimeError:
        return False
    async with client as wb:
        return await _execute_rotation(
            session, test.tenant_id, abtest_id, nm_id, first_variant, wb
        )


async def apply_winner_variant(
    session: AsyncSession, abtest_id: int, variant_id: int
) -> bool:
    """Финализация — грузим победителя, помечаем тест completed + archived."""
    test = await session.get(AbTest, abtest_id)
    if test is None:
        raise ValueError(f"abtest {abtest_id} not found")
    variant = await session.get(AbTestVariant, variant_id)
    if variant is None or variant.abtest_id != abtest_id:
        raise ValueError(f"variant {variant_id} not found in abtest {abtest_id}")
    nm_id = await _nm_id_for_test(session, test)
    if nm_id is None:
        raise ValueError(f"abtest {abtest_id} has no product (nm_id={test.nm_id})")
    client = await wb_client_for_tenant(session, test.tenant_id)
    async with client as wb:
        ok = await _execute_rotation(
            session, test.tenant_id, abtest_id, nm_id, variant, wb
        )
    now = datetime.now(timezone.utc)
    test.status = "completed"
    test.completed_at = now
    test.archived_at = now
    return ok


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


async def _nm_id_for_test(session: AsyncSession, test: AbTest) -> int | None:
    """test.nm_id — FK → products.nm_id. Просто возвращаем поле, продукт-чек
    делает caller (тест с несуществующим FK невозможен из-за CASCADE)."""
    # Тонкий sanity-check: продукт может быть архивирован.
    prod = await session.get(Product, test.nm_id)
    if prod is None:
        return None
    return int(test.nm_id)


async def _live_variants(
    session: AsyncSession, abtest_id: int
) -> list[AbTestVariant]:
    return (
        await session.execute(
            select(AbTestVariant)
            .where(
                AbTestVariant.abtest_id == abtest_id,
                AbTestVariant.eliminated_at.is_(None),
            )
            .order_by(AbTestVariant.label)
        )
    ).scalars().all()


async def _last_successful_rotation(
    session: AsyncSession, abtest_id: int
) -> AbTestRotation | None:
    return (
        await session.execute(
            select(AbTestRotation)
            .where(
                AbTestRotation.abtest_id == abtest_id,
                AbTestRotation.success.is_(True),
            )
            .order_by(AbTestRotation.applied_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _check_and_rotate_one(
    session: AsyncSession, test: AbTest, wb: WbApiClient
) -> bool:
    live = await _live_variants(session, test.id)
    if len(live) < 2:
        return False

    last_rotation = await _last_successful_rotation(session, test.id)
    last_on_eliminated = (
        last_rotation is not None
        and not any(v.id == last_rotation.variant_id for v in live)
    )
    if last_rotation is not None and not last_on_eliminated:
        current = next(
            (v for v in live if v.id == last_rotation.variant_id),
            None,
        )
    else:
        current = live[0]
    if current is None:
        return False

    should_rotate = await _check_trigger(session, test, current, last_rotation)
    if not should_rotate:
        # TIME-триггер — точечно перепланировать на оставшееся время.
        # Self-schedule пока stub (Phase 5).
        if test.trigger_mode == "TIME":
            since = (
                last_rotation.applied_at
                if last_rotation is not None
                else (test.started_at or datetime.now(timezone.utc))
            )
            remaining_s = test.trigger_value * 60 - (
                datetime.now(timezone.utc) - since
            ).total_seconds()
            if remaining_s > 0:
                await _schedule_test_rotation_check(test.id, remaining_s)
        return False

    # Pre-rotation snapshot: фиксирует cumulative показы текущего варианта.
    await _sync_stats_for_tests([test.id], quick=False)

    idx = next(i for i, v in enumerate(live) if v.id == current.id)
    next_v = live[(idx + 1) % len(live)]
    log.info("[rotation] test %d: %s → %s", test.id, current.label, next_v.label)

    nm_id = await _nm_id_for_test(session, test)
    if nm_id is None:
        log.warning("[rotation] test %d: no nm_id (product gone?)", test.id)
        return False

    ok = await _execute_rotation(session, test.tenant_id, test.id, nm_id, next_v, wb)

    if ok:
        if test.trigger_mode == "TIME":
            await _schedule_test_rotation_check(test.id, test.trigger_value * 60)
    else:
        # Быстрый retry через 2 мин, не дожидаясь beat cycle (15 мин).
        log.warning(
            "[rotation] test %d: rotation failed, retry scheduled in 2 min", test.id
        )
        await _schedule_test_rotation_check(test.id, 2 * 60)
    return True


async def _check_trigger(
    session: AsyncSession,
    test: AbTest,
    current: AbTestVariant,
    last_rotation: AbTestRotation | None,
) -> bool:
    """VIEWS / TIME / BUDGET → True если пора ротировать."""
    if test.trigger_mode == "VIEWS":
        since = (
            last_rotation.applied_at
            if last_rotation is not None
            else (test.started_at or datetime.fromtimestamp(0, timezone.utc))
        )
        # Для BOTH считаем только adv-показы — иначе double-count
        # (nm-report.openCount уже включает adv-клики).
        source_filter = "adv" if test.traffic_source == "BOTH" else None
        impressions = await get_impressions_for_variant_since(
            session, current.id, since, source_filter
        )
        log.info(
            "[rotation] test %d VIEWS: %d/%d%s",
            test.id, impressions, test.trigger_value,
            f" (source={source_filter})" if source_filter else "",
        )
        return impressions >= test.trigger_value

    if test.trigger_mode == "TIME":
        since = (
            last_rotation.applied_at
            if last_rotation is not None
            else (test.started_at or datetime.fromtimestamp(0, timezone.utc))
        )
        elapsed_min = (datetime.now(timezone.utc) - since).total_seconds() / 60.0
        log.info(
            "[rotation] test %d TIME: %d/%d min",
            test.id, round(elapsed_min), test.trigger_value,
        )
        return elapsed_min >= test.trigger_value

    if test.trigger_mode == "BUDGET":
        # ANY-тесты без adv-источника не могут считать spend → не триггерим.
        if test.traffic_source == "ANY":
            return False
        since = (
            last_rotation.applied_at
            if last_rotation is not None
            else (test.started_at or datetime.fromtimestamp(0, timezone.utc))
        )
        base = await latest_adv_snapshot_at_or_before(session, test.id, since)
        latest = await latest_adv_snapshot(session, test.id)
        if base is None or latest is None:
            log.info("[rotation] test %d BUDGET: no snapshots yet", test.id)
            return False
        spent = max(0.0, float(latest.cum_ad_spend) - float(base.cum_ad_spend))
        log.info(
            "[rotation] test %d BUDGET: %.2f₽ / %d₽",
            test.id, spent, test.trigger_value,
        )
        return spent >= float(test.trigger_value)

    return False


async def _execute_rotation(
    session: AsyncSession,
    tenant_id: int,
    abtest_id: int,
    nm_id: int,
    variant: AbTestVariant,
    wb: WbApiClient,
) -> bool:
    """Загружает все фото варианта на WB. Пишет 1 запись в `abtest_rotation`.

    success=True ТОЛЬКО если все фото варианта успешно загружены. Partial:
    success=False, error содержит список упавших фото.
    """
    photos = (
        await session.execute(
            select(AbTestVariantPhoto)
            .where(AbTestVariantPhoto.variant_id == variant.id)
            .order_by(AbTestVariantPhoto.photo_order)
        )
    ).scalars().all()

    if not photos:
        session.add(
            AbTestRotation(
                tenant_id=tenant_id,
                abtest_id=abtest_id,
                variant_id=variant.id,
                success=False,
                error="no photos to upload",
            )
        )
        return False

    failures: list[str] = []
    any_ok = False
    last_response: dict | None = None

    for i, p in enumerate(photos):
        if i > 0:
            await asyncio.sleep(PHOTO_UPLOAD_PAUSE_S)
        try:
            file_bytes = await photo_storage.read_variant_photo(p.photo_path)
        except FileNotFoundError as e:
            failures.append(f"#{p.photo_order}: file not found {e}")
            log.error(
                "[rotation] test %d photo #%d: file not found at %s",
                abtest_id, p.photo_order, p.photo_path,
            )
            continue

        ext = Path(p.photo_path).suffix
        ctype = p.content_type or photo_storage.photo_ext_to_mime(ext)
        try:
            resp = await content_media.upload_media_file(
                wb,
                nm_id=nm_id,
                photo_number=p.photo_order,
                file_bytes=file_bytes,
                filename=f"photo{ext}",
                content_type=ctype,
            )
            if isinstance(resp, dict):
                last_response = resp
            any_ok = True
            log.info(
                "[rotation] test %d: photo #%d uploaded OK", abtest_id, p.photo_order
            )
        except WbApiError as e:
            failures.append(f"#{p.photo_order}: WB {e.status} {e.message}")
            log.error(
                "[rotation] test %d photo #%d failed — WB %d: %s",
                abtest_id, p.photo_order, e.status, e.message,
            )
        except Exception as e:
            failures.append(f"#{p.photo_order}: {type(e).__name__}: {e}")
            log.error(
                "[rotation] test %d photo #%d failed — %s",
                abtest_id, p.photo_order, e,
            )

    success = any_ok and not failures
    error_str: str | None = None
    if failures:
        error_str = f"partial failure ({len(failures)}/{len(photos)}): " + "; ".join(
            failures
        )

    session.add(
        AbTestRotation(
            tenant_id=tenant_id,
            abtest_id=abtest_id,
            variant_id=variant.id,
            success=success,
            wb_response=last_response,
            error=error_str,
        )
    )
    return success


# ----------------------------------------------------------------------
# Stubs for cross-phase deps (will be wired up later)
# ----------------------------------------------------------------------


async def _schedule_test_rotation_check(abtest_id: int, delay_s: float) -> None:
    """Self-scheduled per-test ротация — будет реализована в Phase 5 как
    `celery_app.send_task("...", args=[abtest_id], countdown=delay_s)`.

    Пока no-op: beat-cycle (15 мин) подберёт тест на следующем тике. Это
    означает чуть «худшую» точность TIME-триггера (±15 мин) и медленный
    retry после ошибок ротации (тоже до 15 мин). После Phase 5 — точно по
    countdown.
    """
    log.debug(
        "[rotation] would schedule test %d in %.1f sec (TODO Phase 5)",
        abtest_id, delay_s,
    )


async def _sync_stats_for_tests(
    abtest_ids: Sequence[int], quick: bool = False
) -> None:
    """Pre-rotation stats sync — будет реализован в Phase 3b-ii в `stats.py`.

    Стейк (что должно быть): сходить в nm-report и adv API, дописать
    abtest_daily_stat и снять snapshot в abtest_stats_snapshot ДО смены
    фото — чтобы дельта показов после ротации правильно атрибутировалась
    к новому варианту.

    Сейчас no-op: snapshot'ы не накапливаются → BUDGET-триггер не работает,
    VIEWS-триггер тоже (нет данных в abtest_daily_stat). TIME-триггер
    работает независимо. Это сознательное упрощение Phase 3b-i — после
    Phase 3b-ii все триггеры заработают.
    """
    log.debug(
        "[rotation] would sync stats for tests %s (TODO Phase 3b-ii)",
        list(abtest_ids),
    )
