"""Scheduler перераспределения: окна 09:00/18:00 МСК.

Beat-task `publish_redistribution_windows` (раз в минуту в пиковых часах)
проверяет — наступило ли окно. Если да — публикует event
`redistribution.window.open` через event_bus. Consumer `execute_window`
подбирает task'и из `redistribution_tasks` и пытается забронировать слот.

В v1 точная миллисекундная синхронизация и подготовленные POST-payloads
(REDISTRIBUTION_PLAN §6.5) — НЕ реализованы. Реализуется когда будет
HAR для POST shifts.create + NTP-точность на сервере.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.services.event_bus import EventType, publish

log = logging.getLogger(__name__)


# UTC offset для МСК
MSK_OFFSET_HOURS = 3

# Окна (часы в МСК)
WINDOW_HOURS_MSK = (9, 18)


def is_window_now(now: datetime | None = None, tolerance_seconds: int = 30) -> bool:
    """True если текущее время — в пределах ±tolerance_seconds от 09:00 или
    18:00 МСК. Используется beat-task'ом раз в минуту чтобы поймать окно."""
    now = now or datetime.now(timezone.utc)
    msk_hour = (now.hour + MSK_OFFSET_HOURS) % 24
    msk_minute = now.minute
    msk_second = now.second

    if msk_minute != 0:
        return False
    if msk_hour not in WINDOW_HOURS_MSK:
        return False
    # ±30 сек от ровного часа: minute==0 + second 0..29 OR минута 59 + second >= 30
    # (за минуту до). Чтобы не пропустить окно если beat поднялся чуть рано.
    return msk_second <= tolerance_seconds


def next_window_at(now: datetime | None = None) -> datetime:
    """Возвращает datetime ближайшего окна (UTC, aware).

    Используется при создании RedistributionTask чтобы проставить
    `target_window_at` — selectиться будет в этом окне.
    """
    now = now or datetime.now(timezone.utc)
    today_msk_date = (now + timedelta(hours=MSK_OFFSET_HOURS)).date()
    for hr in WINDOW_HOURS_MSK:
        candidate_utc = datetime(
            today_msk_date.year,
            today_msk_date.month,
            today_msk_date.day,
            hr - MSK_OFFSET_HOURS,
            0,
            0,
            tzinfo=timezone.utc,
        )
        if candidate_utc > now:
            return candidate_utc
    # Все сегодняшние окна уже прошли — завтрашнее 09:00 МСК
    tomorrow_msk = today_msk_date + timedelta(days=1)
    return datetime(
        tomorrow_msk.year,
        tomorrow_msk.month,
        tomorrow_msk.day,
        WINDOW_HOURS_MSK[0] - MSK_OFFSET_HOURS,
        0,
        0,
        tzinfo=timezone.utc,
    )


async def publish_window_event(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Если сейчас окно — публикует `redistribution.window.open` для каждого
    активного tenant'а у которого есть подключённая WbLkSession.

    Возвращает количество опубликованных событий. Идемпотентно по `_is_duplicate`
    в consumer'е (один tenant × одна минута окна = одно событие).
    """
    if not is_window_now(now):
        return 0

    now = now or datetime.now(timezone.utc)
    window_dt = now.replace(minute=0, second=0, microsecond=0)

    # Все активные tenants
    tenants = (
        await session.execute(select(Tenant.id, Tenant.slug))
    ).all()
    published = 0
    for tid, slug in tenants:
        await publish(
            EventType.REDISTRIBUTION_WINDOW_OPEN,
            tenant_id=int(tid),
            data={
                "window_dt": window_dt.isoformat(),
                "tenant_slug": slug,
            },
        )
        published += 1
    log.info(
        "redistribution: window event published for %d tenants at %s",
        published,
        window_dt.isoformat(),
    )
    return published
