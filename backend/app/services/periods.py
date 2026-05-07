from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

PeriodKey = Literal["day", "week", "month", "custom"]


@dataclass(frozen=True)
class Period:
    key: PeriodKey
    start: datetime
    end: datetime
    prev_start: datetime
    prev_end: datetime

    @property
    def days(self) -> int:
        return max(1, int((self.end - self.start).total_seconds() // 86400) or 1)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_period(key: PeriodKey, now: datetime | None = None) -> Period:
    now = now or now_utc()
    end = now
    if key == "day":
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    elif key == "week":
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif key == "month":
        start = (end - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown period: {key}")
    span = end - start
    prev_end = start
    prev_start = prev_end - span
    return Period(key=key, start=start, end=end, prev_start=prev_start, prev_end=prev_end)


def period_from_range(start_date: date, end_date: date) -> Period:
    """Build a custom Period from inclusive [start_date, end_date].

    Previous-comparison window has the same length, ending at start.
    """
    if end_date < start_date:
        raise ValueError("end_date must be >= start_date")
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    span = end - start
    prev_end = start
    prev_start = prev_end - span
    return Period(key="custom", start=start, end=end, prev_start=prev_start, prev_end=prev_end)
