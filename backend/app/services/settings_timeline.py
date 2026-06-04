"""Date-effective settings lookup.

Some settings (tax system, tax rate, VAT rate) change over time — usually because
of legislation. Storing only the *current* value loses the ability to recompute
historical P&L correctly. This module adds a per-date timeline:

  AppSetting       — current static value (single row per key)
  SettingTimeline  — list of {key, value, effective_from, comment}

For a given calendar date `d`, the effective value of a timelined key is:
    1. the timeline entry with the greatest `effective_from <= d`, OR
    2. the static AppSetting value if no timeline entry covers that date.

That way the user can leave AppSetting as the historical default and only add
timeline entries at moments when the value changed (e.g. "VAT 22% from
2026-01-01" while AppSetting stays at "20").
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, SettingTimeline

# Keys that are allowed to have date-effective overrides. Keep narrow to avoid
# accidentally timeline-ing thresholds that should always apply uniformly
# (e.g. fixed_costs_monthly is a forward-looking allocation, not a historical
# fact). Tax/VAT are the canonical case.
TIMELINEABLE_KEYS: frozenset[str] = frozenset(
    {
        "tax_system",
        "tax_rate",
        "tax_min_rate",
        "reduce_by_insurance",
        "vat_payer",
        "vat_rate",
    }
)


async def load_timeline(
    session: AsyncSession,
) -> dict[str, list[tuple[date, str | None]]]:
    """Return {key: [(effective_from, value), ...]} sorted ASC by date."""
    rows = (
        await session.execute(
            select(
                SettingTimeline.key,
                SettingTimeline.effective_from,
                SettingTimeline.value,
            ).order_by(SettingTimeline.key, SettingTimeline.effective_from)
        )
    ).all()
    out: dict[str, list[tuple[date, str | None]]] = {}
    for r in rows:
        out.setdefault(r.key, []).append((r.effective_from, r.value))
    return out


def value_for_date(
    timeline: dict[str, list[tuple[date, str | None]]],
    static: dict[str, str],
    key: str,
    on_date: date,
) -> str | None:
    """Pick the value of `key` valid on `on_date`.

    Lookup order:
        1. Latest timeline entry where effective_from <= on_date.
        2. Static AppSetting value.
        3. None.
    """
    series = timeline.get(key) or []
    if series:
        dates = [d for d, _ in series]
        idx = bisect_right(dates, on_date) - 1
        if idx >= 0:
            return series[idx][1]
    return static.get(key)


def make_lookup(
    timeline: dict[str, list[tuple[date, str | None]]],
    static: dict[str, str],
):
    """Curry: returns a `lookup(key, on_date)` closure for use in hot loops."""

    def _lookup(key: str, on_date: date) -> str | None:
        return value_for_date(timeline, static, key, on_date)

    return _lookup


# ---------------------------------------------------------------------------
# Static-config helper (kept here so callers don't need to import AppSetting)
# ---------------------------------------------------------------------------


async def load_static_settings(session: AsyncSession) -> dict[str, str]:
    # AppSetting НЕ TenantScopedMixin → глобальный tenant-фильтр (do_orm_execute)
    # на неё НЕ распространяется. Без явного фильтра `select(AppSetting)` тянет
    # настройки ВСЕХ кабинетов, и dict схлопывается по key (выигрывает
    # произвольный tenant) — так чужой tax_rate/tax_system перетирал наш.
    from app.services.tenant_context import get_tenant  # noqa: WPS433

    stmt = select(AppSetting)
    tid = get_tenant(session)
    if tid is not None:
        stmt = stmt.where(AppSetting.tenant_id == tid)
    rows = (await session.execute(stmt)).scalars().all()
    return {r.key: (r.value or "") for r in rows}


def is_timelineable(key: str) -> bool:
    return key in TIMELINEABLE_KEYS


def parse_value(key: str, raw: str | None) -> Any:
    """Coerce string-form value to its semantic Python type for `key`.

    Used by tax/VAT computations in pnl_builder where they expect floats/bools.
    Unknown keys return the raw string.
    """
    if raw is None or raw == "":
        return None
    if key in ("vat_payer", "reduce_by_insurance"):
        return raw == "1" or raw.lower() in ("true", "yes")
    if key == "tax_system":
        return raw
    # numeric keys
    try:
        return float(raw)
    except ValueError:
        return None
