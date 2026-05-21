"""Тесты pure-функции `simulate_promo` (TASK-LEAD-050).

Чисто математические — без БД. Проверяем 5 кейсов:

1. **Profitable** — высокая маржа, скромный boost → акция прибыльна.
2. **Unprofitable** — большая скидка, маленький boost → убыток.
3. **Breakeven** — boost ровно компенсирует скидку → margin_total ≈ baseline.
4. **Tight margin** — маржа после скидки = 0 → margin_total = 0.
5. **Capped boost** — даже при 500% boost убыток → breakeven=None.
"""
from __future__ import annotations

from app.services.promo_calculator import SkuBaseline, simulate_promo


def _bl(
    *,
    avg_price: float,
    velocity: float,
    margin_per_unit: float,
    cogs_per_unit: float,
    commission_rate: float = 0.20,
    logistics_per_unit: float = 50.0,
    buyout_rate: float = 1.0,
) -> SkuBaseline:
    """Build a fixture baseline with sane derived fields."""
    return SkuBaseline(
        nm_id=12345,
        vendor_code="TEST-001",
        brand="TestBrand",
        photo_url=None,
        days_in_window=14,
        units_sold=int(velocity * 14),
        revenue_per_day=velocity * avg_price,
        velocity_per_day=velocity,
        avg_price=avg_price,
        buyout_rate=buyout_rate,
        margin_per_unit=margin_per_unit,
        commission_rate=commission_rate,
        logistics_per_unit=logistics_per_unit,
        cogs_per_unit=cogs_per_unit,
    )


def test_profitable_promo():
    """Маржа крупная, скидка умеренная, boost достаточный → акция выгодна."""
    bl = _bl(
        avg_price=1000.0,
        velocity=10.0,
        cogs_per_unit=200.0,
        # margin = 1000 − 200 − 200(20% comm) − 50(log) = 550
        margin_per_unit=550.0,
    )
    r = simulate_promo(
        bl, discount_pct=15.0, duration_days=7, expected_velocity_boost_pct=100.0
    )
    # При −15% и +100% velocity: new_price=850, new_margin_per_unit = 850 − 200 − 170 − 50 = 430
    # margin_per_day = 430 × (10 × 2) = 8600; baseline = 550 × 10 = 5500.
    assert r.is_profitable, "new_margin_per_unit > 0 — profitable"
    assert r.is_better_than_baseline, "8600/day > 5500/day baseline"
    assert r.delta_pct["margin_total"] is not None
    assert r.delta_pct["margin_total"] > 0
    # Breakeven boost — должен быть достижим и ниже 100%.
    assert r.breakeven_velocity_boost_pct is not None
    assert 0.0 <= r.breakeven_velocity_boost_pct <= 100.0


def test_unprofitable_promo():
    """Большая скидка, мизерный boost → убыток vs baseline."""
    bl = _bl(
        avg_price=500.0,
        velocity=5.0,
        cogs_per_unit=200.0,
        # margin = 500 − 200 − 100(20% comm) − 50 = 150
        margin_per_unit=150.0,
    )
    r = simulate_promo(
        bl, discount_pct=40.0, duration_days=14, expected_velocity_boost_pct=10.0
    )
    # new_price = 300; new_margin = 300 − 200 − 60 − 50 = −10 (убыток)
    assert not r.is_profitable, "new_margin_per_unit < 0 — unprofitable"
    assert not r.is_better_than_baseline
    assert r.delta_abs["margin_total"] < 0
    # Если new_margin_per_unit < 0 — breakeven недостижим
    assert r.breakeven_velocity_boost_pct is None


def test_breakeven_approx():
    """Boost ровно подобран → margin_total ≈ baseline. Проверяем что
    breakeven_velocity_boost_pct отражает реальную точку безубытка.
    """
    bl = _bl(
        avg_price=1000.0,
        velocity=10.0,
        cogs_per_unit=300.0,
        # margin = 1000 − 300 − 200(20%) − 50 = 450
        margin_per_unit=450.0,
    )
    # Скидка 20%: new_price=800, new_margin_per_unit = 800 − 300 − 160 − 50 = 290
    # Чтобы margin_total стал = baseline: 290 × velocity_new × duration
    #   = 450 × 10 × duration ⇒ velocity_new = 4500/290 = 15.52
    # ⇒ boost = (15.52 − 10) / 10 × 100 = 55.2%
    r = simulate_promo(
        bl, discount_pct=20.0, duration_days=7, expected_velocity_boost_pct=0.0
    )
    assert r.breakeven_velocity_boost_pct is not None
    assert 50.0 <= r.breakeven_velocity_boost_pct <= 60.0
    # Теперь подадим этот boost — должен быть ≈ break-even.
    r2 = simulate_promo(
        bl,
        discount_pct=20.0,
        duration_days=7,
        expected_velocity_boost_pct=r.breakeven_velocity_boost_pct,
    )
    # Допуск 2% из-за округления breakeven до 1 знака.
    assert (
        abs(r2.delta_abs["margin_total"]) / max(1.0, abs(r2.baseline["margin_total"]))
        < 0.02
    )


def test_zero_margin_after_discount():
    """Скидка ровно съедает всю маржу → new_margin_per_unit ≈ 0."""
    bl = _bl(
        avg_price=500.0,
        velocity=10.0,
        cogs_per_unit=350.0,
        commission_rate=0.20,
        logistics_per_unit=50.0,
        # margin = 500 − 350 − 100 − 50 = 0
        margin_per_unit=0.0,
    )
    # Любая скидка делает убыток. Baseline = 0 → cannot compute delta_pct.
    r = simulate_promo(
        bl, discount_pct=5.0, duration_days=7, expected_velocity_boost_pct=50.0
    )
    assert not r.is_profitable
    # delta_pct['margin_per_unit'] = None потому что baseline=0 (div-by-zero).
    assert r.delta_pct["margin_per_unit"] is None or r.delta_pct["margin_total"] is None


def test_capped_breakeven_returns_none_for_extreme_loss():
    """Если new_margin_per_unit отрицательная (даже без скидки убыток в каком-то
    кейсе) — breakeven недостижим, None.
    """
    bl = _bl(
        avg_price=500.0,
        velocity=10.0,
        cogs_per_unit=450.0,
        commission_rate=0.20,
        logistics_per_unit=50.0,
        # margin = 500 − 450 − 100 − 50 = -100
        margin_per_unit=-100.0,
    )
    r = simulate_promo(
        bl, discount_pct=30.0, duration_days=7, expected_velocity_boost_pct=200.0
    )
    # new_margin_per_unit = 350 − 450 − 70 − 50 = -220, ещё хуже.
    assert not r.is_profitable
    assert r.breakeven_velocity_boost_pct is None


def test_input_sanity_caps():
    """discount > 99% и boost > 1000% капируются (не падаем, не уходим в инф.)."""
    bl = _bl(
        avg_price=1000.0,
        velocity=5.0,
        cogs_per_unit=200.0,
        margin_per_unit=550.0,
    )
    # Передаём заведомо неадекватные значения — функция должна clamp'нуть.
    r = simulate_promo(
        bl, discount_pct=150.0, duration_days=7, expected_velocity_boost_pct=5000.0
    )
    # discount cap=99% → new_price = 10
    assert r.with_promo["avg_price"] == 10.0
    # boost cap=1000% → new_velocity = 5 × 11 = 55
    assert abs(r.with_promo["velocity_per_day"] - 55.0) < 1e-6
