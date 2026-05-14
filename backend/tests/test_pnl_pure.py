"""Pure-function тесты для pnl_builder — без БД.

Покрываем: _bucket_key (day/week/month), cost_for_date (с историей COGS),
_compute_tax (УСН-6/15, ОСН, АУСН, ПСН), _compute_tax_for_fns (бухгалтерская
методика).
"""
from datetime import date

import pytest

from app.services.pnl_builder import (
    _bucket_key,
    _compute_tax,
    _compute_tax_for_fns,
    cost_for_date,
)


# ── _bucket_key ──────────────────────────────────────────────────────


def test_bucket_key_day():
    d = date(2026, 4, 15)
    assert _bucket_key(d, "day") == (d, d)


def test_bucket_key_week_monday_to_sunday():
    # 2026-04-15 — среда. Понедельник = 13.04, воскресенье = 19.04.
    start, end = _bucket_key(date(2026, 4, 15), "week")
    assert start == date(2026, 4, 13)
    assert end == date(2026, 4, 19)
    assert start.weekday() == 0
    assert end.weekday() == 6


def test_bucket_key_month_april():
    start, end = _bucket_key(date(2026, 4, 15), "month")
    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_bucket_key_month_december_rolls_over():
    """Регресс: month-key для декабря не должен крашиться на month+1."""
    start, end = _bucket_key(date(2026, 12, 15), "month")
    assert start == date(2026, 12, 1)
    assert end == date(2026, 12, 31)


def test_bucket_key_invalid_granularity_raises():
    with pytest.raises(ValueError):
        _bucket_key(date(2026, 4, 15), "year")  # type: ignore[arg-type]


# ── cost_for_date ─────────────────────────────────────────────────────


def test_cost_for_date_empty_lookup_returns_zero():
    assert cost_for_date({}, 123, date(2026, 4, 15)) == 0.0


def test_cost_for_date_picks_latest_valid_from_le_date():
    """История COGS:
      01.01.2026 → 100₽
      01.03.2026 → 120₽
      01.06.2026 → 150₽

    Продажа 15.04.2026 → должна вернуть 120 (последний valid_from ≤ 15.04).
    """
    lookup = {
        100: [
            (date(2026, 1, 1), 100.0),
            (date(2026, 3, 1), 120.0),
            (date(2026, 6, 1), 150.0),
        ]
    }
    assert cost_for_date(lookup, 100, date(2026, 4, 15)) == 120.0


def test_cost_for_date_before_first_entry_falls_back_to_earliest():
    """Если продажа раньше первой записи — используем самую раннюю
    известную себестоимость. Альтернатива (0) была бы хуже — занижала бы
    прибыль за исторический период."""
    lookup = {100: [(date(2026, 3, 1), 120.0), (date(2026, 6, 1), 150.0)]}
    assert cost_for_date(lookup, 100, date(2026, 1, 15)) == 120.0


def test_cost_for_date_after_last_entry_uses_last():
    lookup = {100: [(date(2026, 3, 1), 120.0), (date(2026, 6, 1), 150.0)]}
    assert cost_for_date(lookup, 100, date(2027, 1, 1)) == 150.0


def test_cost_for_date_unknown_nm_returns_zero():
    lookup = {100: [(date(2026, 3, 1), 120.0)]}
    assert cost_for_date(lookup, 999, date(2026, 4, 15)) == 0.0


# ── _compute_tax — управленческий ────────────────────────────────────

TAX_KWARGS_BASE = dict(
    revenue_net=1_000_000.0,
    revenue_after_vat=1_000_000.0,
    expenses=600_000.0,
    tax_rate=6.0,
    tax_min_rate=0.0,
    reduce_by_insurance=False,
    cash_income=None,
)


def test_tax_usn_income_6pct():
    """УСН-доход: 6% от revenue (без cash_income override)."""
    tax = _compute_tax("usn_income", **TAX_KWARGS_BASE)
    assert tax == pytest.approx(60_000.0)


def test_tax_usn_income_uses_cash_income_when_provided():
    """Если передан cash_income — налог идёт от ppvz_net, не от retail."""
    tax = _compute_tax(
        "usn_income",
        **{**TAX_KWARGS_BASE, "cash_income": 800_000.0},
    )
    assert tax == pytest.approx(48_000.0)


def test_tax_usn_income_reduce_by_insurance_halves():
    tax = _compute_tax(
        "usn_income",
        **{**TAX_KWARGS_BASE, "reduce_by_insurance": True},
    )
    assert tax == pytest.approx(30_000.0)


def test_tax_usn_income_expense_15pct_with_min_tax():
    """УСН-15: max(15% * (revenue − expenses), 1% * revenue)."""
    tax = _compute_tax(
        "usn_income_expense",
        revenue_net=1_000_000.0,
        revenue_after_vat=1_000_000.0,
        expenses=600_000.0,
        tax_rate=15.0,
        tax_min_rate=1.0,
        reduce_by_insurance=False,
    )
    # base = 1M − 600k = 400k; 15% = 60k; min = 1% × 1M = 10k. Берём max = 60k.
    assert tax == pytest.approx(60_000.0)


def test_tax_usn_income_expense_min_tax_kicks_in_when_no_profit():
    """Если расходы > доходов — налог = min_tax = 1% от выручки."""
    tax = _compute_tax(
        "usn_income_expense",
        revenue_net=1_000_000.0,
        revenue_after_vat=1_000_000.0,
        expenses=1_200_000.0,
        tax_rate=15.0,
        tax_min_rate=1.0,
        reduce_by_insurance=False,
    )
    assert tax == pytest.approx(10_000.0)


def test_tax_osn_25pct_on_profit():
    tax = _compute_tax(
        "osn",
        revenue_net=1_000_000.0,
        revenue_after_vat=1_000_000.0,
        expenses=600_000.0,
        tax_rate=25.0,
        tax_min_rate=0.0,
        reduce_by_insurance=False,
    )
    assert tax == pytest.approx(100_000.0)


def test_tax_patent_is_zero():
    tax = _compute_tax(
        "patent",
        revenue_net=10_000_000.0,
        revenue_after_vat=10_000_000.0,
        expenses=0.0,
        tax_rate=99.0,
        tax_min_rate=0.0,
        reduce_by_insurance=False,
    )
    assert tax == 0.0


def test_tax_none_system_returns_zero():
    tax = _compute_tax(
        "none",
        revenue_net=1_000_000.0,
        revenue_after_vat=1_000_000.0,
        expenses=0.0,
        tax_rate=20.0,
        tax_min_rate=0.0,
        reduce_by_insurance=False,
    )
    assert tax == 0.0


def test_tax_negative_revenue_clamps_to_zero():
    """Защита от отрицательной выручки — налог не уходит в минус."""
    tax = _compute_tax(
        "usn_income",
        revenue_net=-100_000.0,
        revenue_after_vat=-100_000.0,
        expenses=0.0,
        tax_rate=6.0,
        tax_min_rate=0.0,
        reduce_by_insurance=False,
    )
    assert tax == 0.0


# ── _compute_tax_for_fns — бухгалтерская методика ────────────────────


def test_tax_for_fns_usn_income_15pct_methodology():
    """Бухгалтер: доход − wb_expenses (УПД-удержания) − cogs."""
    tax = _compute_tax_for_fns(
        "usn_income_expense",
        retail_amt_net=1_000_000.0,
        ppvz_vw_net=100_000.0,
        ppvz_vw_nds_net=20_000.0,
        delivery=50_000.0,
        paid_acceptance=10_000.0,
        penalty=5_000.0,
        deduction=0.0,
        storage=15_000.0,
        cogs=400_000.0,
        tax_rate=15.0,
        tax_min_rate=1.0,
        reduce_by_insurance=False,
    )
    # wb_expenses = 100+20+50+10+5+0+15 = 200k
    # base = 1M − 200k − 400k = 400k
    # 15% * 400k = 60k vs min 1%*1M = 10k → 60k
    assert tax == pytest.approx(60_000.0)


def test_tax_for_fns_ausn_income_doc_methodology():
    """АУСН-доход: 8% от income (не зависит от расходов)."""
    tax = _compute_tax_for_fns(
        "ausn_income",
        retail_amt_net=1_000_000.0,
        ppvz_vw_net=999_999.0,  # игнорится для -доход системы
        ppvz_vw_nds_net=0.0,
        delivery=0.0,
        paid_acceptance=0.0,
        penalty=0.0,
        deduction=0.0,
        storage=0.0,
        cogs=999_999.0,
        tax_rate=8.0,
        tax_min_rate=0.0,
        reduce_by_insurance=False,
    )
    assert tax == pytest.approx(80_000.0)
