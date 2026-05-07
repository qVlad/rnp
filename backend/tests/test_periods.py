from datetime import datetime, timezone

from app.services.periods import get_period


def test_day_period_starts_at_midnight():
    now = datetime(2026, 4, 30, 14, 30, tzinfo=timezone.utc)
    p = get_period("day", now)
    assert p.start.hour == 0
    assert p.start.minute == 0
    assert p.end == now
    assert p.prev_end == p.start
    assert (p.start - p.prev_start).total_seconds() > 0


def test_week_period_spans_seven_days():
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    p = get_period("week", now)
    assert (p.end - p.start).days == 6


def test_month_period_spans_thirty_days():
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    p = get_period("month", now)
    assert (p.end - p.start).days == 29
