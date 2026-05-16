"""Unit-тесты на порт `significance.ts` → `significance.py`.

Math должна совпадать с TS-оригиналом до 4-5 знаков после запятой (TS
использовал A&S-аппроксимацию, мы — math.erf; разница порядка 1e-7).
"""
from app.services.abtest.significance import (
    SignificanceReport,
    VariantStats,
    compute_significance,
    wilson_ci,
    z_test,
)


# ---------- z_test ----------

def test_z_test_strong_signal():
    # 5% vs 10% on n=1000 — должно быть очень значимо (p < 0.001)
    r = z_test(50, 1000, 100, 1000, alpha=0.05)
    assert r.significant is True
    assert r.p_value < 0.001
    assert r.z_score < 0  # A хуже B


def test_z_test_no_signal():
    # одинаковые пропорции → p близко к 1
    r = z_test(50, 1000, 50, 1000, alpha=0.05)
    assert r.significant is False
    assert r.p_value > 0.9


def test_z_test_empty_inputs():
    r = z_test(0, 0, 0, 0)
    assert r.p_value == 1.0
    assert r.significant is False


def test_z_test_borderline():
    # ~5% разница на достаточной выборке должна быть значима
    r = z_test(100, 1000, 150, 1000, alpha=0.05)
    assert r.significant is True
    assert 0 < r.p_value < 0.05


# ---------- wilson_ci ----------

def test_wilson_ci_zero_observations():
    ci = wilson_ci(0, 100)
    assert ci.center > 0  # Wilson не даёт 0 при n>0 (бесконечно узкий conf)
    assert ci.lower == 0.0
    assert ci.upper < 0.05  # 95% CI верхней границы для 0/100 ≈ 0.037


def test_wilson_ci_symmetric_at_half():
    # 50/100 — center близок к 0.5, интервал симметричный
    ci = wilson_ci(50, 100)
    assert 0.49 < ci.center < 0.51
    assert 0.40 < ci.lower < 0.41
    assert 0.59 < ci.upper < 0.60


def test_wilson_ci_zero_n():
    ci = wilson_ci(0, 0)
    assert ci.lower == 0.0
    assert ci.upper == 0.0
    assert ci.center == 0.0


# ---------- compute_significance ----------

def test_compute_significance_clear_winner():
    variants = [
        VariantStats(variant_id=1, label="A", impressions=2000, clicks=100,
                     cart_adds=50, orders=20),
        VariantStats(variant_id=2, label="B", impressions=2000, clicks=200,
                     cart_adds=100, orders=40),
    ]
    rep = compute_significance(variants, min_sample_size=1500, alpha=0.05)
    assert isinstance(rep, SignificanceReport)
    # B значимо лучше A по CTR (10% vs 5% на 2000 показов)
    assert rep.ctr_winner is not None
    assert rep.ctr_winner.variant_id == 2
    assert rep.ctr_winner.label == "B"
    # pairwise один — A vs B
    assert len(rep.pairwise) == 1
    assert rep.pairwise[0].ctr_test.significant is True


def test_compute_significance_undersampled_no_winner():
    # Сэмпл < min → winner=None даже при значимом p
    variants = [
        VariantStats(variant_id=1, label="A", impressions=300, clicks=10,
                     cart_adds=5, orders=2),
        VariantStats(variant_id=2, label="B", impressions=300, clicks=60,
                     cart_adds=30, orders=15),
    ]
    rep = compute_significance(variants, min_sample_size=1500, alpha=0.05)
    assert rep.ctr_winner is None  # impressions=300 < 1500
    assert rep.sample_progress[0].pct == 20  # 300/1500 = 20%


def test_compute_significance_top_denom_clicks():
    # FUNNEL+ADV: top=cartAdds, denom=clicks (клик → корзина)
    variants = [
        VariantStats(variant_id=1, label="A", impressions=10000, clicks=500,
                     cart_adds=50, orders=10),
        VariantStats(variant_id=2, label="B", impressions=10000, clicks=500,
                     cart_adds=100, orders=20),
    ]
    rep = compute_significance(
        variants, min_sample_size=5000, alpha=0.05,
        top_metric="cartAdds", top_denom="clicks",
    )
    # CTR здесь = cart_adds / clicks → A=10%, B=20%
    assert abs(rep.ctr[1].rate - 0.10) < 0.001
    assert abs(rep.ctr[2].rate - 0.20) < 0.001
    assert rep.ctr_winner is not None
    assert rep.ctr_winner.variant_id == 2


def test_compute_significance_three_variants():
    # Победитель только если значимо лучше ВСЕХ остальных
    variants = [
        VariantStats(variant_id=1, label="A", impressions=2000, clicks=50,
                     cart_adds=20, orders=10),
        VariantStats(variant_id=2, label="B", impressions=2000, clicks=200,
                     cart_adds=100, orders=40),
        VariantStats(variant_id=3, label="C", impressions=2000, clicks=60,
                     cart_adds=25, orders=12),
    ]
    rep = compute_significance(variants, min_sample_size=1500, alpha=0.05)
    # B (10% CTR) значимо лучше A (2.5%) и C (3%)
    assert rep.ctr_winner is not None
    assert rep.ctr_winner.variant_id == 2
    # 3 pairwise: A-B, A-C, B-C
    assert len(rep.pairwise) == 3
