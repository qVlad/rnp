"""Pure-formula tests for /api/dashboard/compare delta math (TASK-LEAD-029).

Avoids DB / FastAPI overhead — exercises just the helper(s) so the math
is locked in (divide-by-zero, equal periods, mixed types).
"""
from __future__ import annotations

from app.api.dashboard_compare import _build_delta_map, _delta_pct


def test_delta_pct_zero_baseline_returns_none() -> None:
    # b == 0 → нельзя делить, отдаём None (UI потом рендерит «—»).
    assert _delta_pct(100, 0) is None
    assert _delta_pct(0, 0) is None
    assert _delta_pct(None, 0) is None


def test_delta_pct_none_inputs_return_none() -> None:
    assert _delta_pct(None, 100) is None
    assert _delta_pct(100, None) is None
    assert _delta_pct(None, None) is None


def test_delta_pct_equal_periods_returns_zero() -> None:
    # period_a == period_b → Δ = 0 %.
    assert _delta_pct(123.45, 123.45) == 0.0
    assert _delta_pct(0.0, 0.0) is None  # zero baseline still None


def test_delta_pct_basic_math() -> None:
    assert _delta_pct(110, 100) == 10.0
    assert _delta_pct(90, 100) == -10.0
    assert _delta_pct(150, 100) == 50.0


def test_delta_pct_rounding() -> None:
    # 1/3 increase → 33.33 %
    assert _delta_pct(133.3333, 100) == 33.33


def test_build_delta_map_period_b_all_zero() -> None:
    """Δ% при period_b со всеми нулевыми KPI = None (не делить на 0)."""
    kpis_a = [
        {"key": "revenue_gross", "value": 100_000},
        {"key": "orders", "value": 50},
        {"key": "margin_pct", "value": 12.5},
    ]
    kpis_b = [
        {"key": "revenue_gross", "value": 0},
        {"key": "orders", "value": 0},
        {"key": "margin_pct", "value": 0},
    ]
    deltas = _build_delta_map(kpis_a, kpis_b)
    assert deltas == {
        "revenue_gross": None,
        "orders": None,
        "margin_pct": None,
    }


def test_build_delta_map_equal_periods_all_zero() -> None:
    """period_a == period_b → Δ = 0 % по всем ненулевым ключам."""
    kpis = [
        {"key": "revenue_gross", "value": 100_000},
        {"key": "orders", "value": 50},
        {"key": "margin_pct", "value": 12.5},
    ]
    deltas = _build_delta_map(kpis, kpis)
    assert deltas == {
        "revenue_gross": 0.0,
        "orders": 0.0,
        "margin_pct": 0.0,
    }


def test_build_delta_map_missing_in_b_returns_none() -> None:
    """KPI, отсутствующий в period_b, → Δ = None (нет baseline'а)."""
    kpis_a = [
        {"key": "revenue_gross", "value": 100},
        {"key": "new_metric", "value": 5},
    ]
    kpis_b = [{"key": "revenue_gross", "value": 80}]
    deltas = _build_delta_map(kpis_a, kpis_b)
    assert deltas["revenue_gross"] == 25.0
    assert deltas["new_metric"] is None
