"""Unit-тесты на snapshot-diff атрибуцию (порт snapshot.ts).

Чистая математика — без DB. Тестируем только `_attribute_interval_to_variants`
и хелперы дат. Интеграционный тест `apply_snapshot` с реальной DB запустим
в Phase 7 smoke.
"""
from datetime import datetime, timezone

from app.services.abtest.snapshot import (
    Rotation,
    VariantRef,
    __test_only__,
)

_attribute = __test_only__["_attribute_interval_to_variants"]
moscow_date_str = __test_only__["moscow_date_str"]
day_key = __test_only__["day_key"]


# ---------- helpers ----------

def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------- attribute_interval_to_variants ----------


def test_attribute_no_rotations_falls_back_to_first_variant():
    """Нет ротаций в интервале — всё уходит первому варианту."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B")]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), variants, [])
    assert shares == {1: 1.0}


def test_attribute_one_rotation_inside():
    """Ротация в середине интервала — 50/50."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B")]
    rotations = [Rotation(2, utc(2026, 5, 17, 11))]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), variants, rotations)
    assert shares[1] == 0.5
    assert shares[2] == 0.5


def test_attribute_rotation_before_interval():
    """Ротация ДО начала интервала — это «текущий вариант на from»."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B")]
    rotations = [
        Rotation(2, utc(2026, 5, 17, 9)),  # до from=10:00
    ]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), variants, rotations)
    assert shares == {2: 1.0}


def test_attribute_three_rotations():
    """Три ротации внутри: 30мин/30мин/30мин/30мин → A=25%, B=25%, C=25%, A=25%."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B"), VariantRef(3, "C")]
    rotations = [
        Rotation(2, utc(2026, 5, 17, 10, 30)),
        Rotation(3, utc(2026, 5, 17, 11)),
        Rotation(1, utc(2026, 5, 17, 11, 30)),
    ]
    shares = _attribute(
        utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), variants, rotations
    )
    # A=10:00-10:30 + 11:30-12:00 = 60 мин (50%)
    # B=10:30-11:00 = 30 мин (25%)
    # C=11:00-11:30 = 30 мин (25%)
    assert abs(shares[1] - 0.5) < 1e-9
    assert abs(shares[2] - 0.25) < 1e-9
    assert abs(shares[3] - 0.25) < 1e-9


def test_attribute_rotation_at_exact_from():
    """Ротация ровно в from = «текущий вариант на from» (включительно)."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B")]
    rotations = [Rotation(2, utc(2026, 5, 17, 10))]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 11), variants, rotations)
    # Ротация applied_at <= from → variant 2 «текущий на from».
    # inside фильтр: from < applied_at < to (строго), 10:00 не входит.
    assert shares == {2: 1.0}


def test_attribute_rotation_at_exact_to_excluded():
    """Ротация ровно в to — НЕ учитывается (строгое неравенство)."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B")]
    rotations = [Rotation(2, utc(2026, 5, 17, 11))]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 11), variants, rotations)
    # applied_at < to (11:00 < 11:00 = False) → rotation отфильтрована
    assert shares == {1: 1.0}


def test_attribute_zero_interval_returns_empty():
    variants = [VariantRef(1, "A")]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 10), variants, [])
    assert shares == {}


def test_attribute_negative_interval_returns_empty():
    variants = [VariantRef(1, "A")]
    shares = _attribute(utc(2026, 5, 17, 12), utc(2026, 5, 17, 10), variants, [])
    assert shares == {}


def test_attribute_empty_variants_returns_empty():
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), [], [])
    assert shares == {}


def test_attribute_shares_sum_to_one():
    """Сумма долей всегда == 1.0 при наличии активности."""
    variants = [VariantRef(1, "A"), VariantRef(2, "B"), VariantRef(3, "C")]
    rotations = [
        Rotation(2, utc(2026, 5, 17, 10, 23)),
        Rotation(3, utc(2026, 5, 17, 11, 7)),
        Rotation(1, utc(2026, 5, 17, 11, 49)),
    ]
    shares = _attribute(utc(2026, 5, 17, 10), utc(2026, 5, 17, 12), variants, rotations)
    assert abs(sum(shares.values()) - 1.0) < 1e-9


# ---------- moscow_date_str ----------


def test_moscow_date_str_utc_midnight_offset():
    """UTC 21:00 = Moscow 00:00 следующего дня (TZ+3)."""
    assert moscow_date_str(utc(2026, 5, 17, 21)) == "2026-05-18"


def test_moscow_date_str_morning():
    """UTC 08:00 = Moscow 11:00 — тот же день."""
    assert moscow_date_str(utc(2026, 5, 17, 8)) == "2026-05-17"


def test_moscow_date_str_dst_does_not_apply():
    """В Москве нет DST — TZ всегда +3. Тест на январь и июль одинаково."""
    assert moscow_date_str(utc(2026, 1, 15, 22)) == "2026-01-16"
    assert moscow_date_str(utc(2026, 7, 15, 22)) == "2026-07-16"


# ---------- day_key ----------


def test_day_key_basic():
    d = day_key("2026-05-17")
    assert d.isoformat() == "2026-05-17"


def test_day_key_iso_with_time_takes_prefix():
    d = day_key("2026-05-17T15:30:00Z")
    assert d.isoformat() == "2026-05-17"
