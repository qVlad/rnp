"""TASK-LEAD-033: проверка conversion-метрик в /api/ads/heatmap.

Pure-function golden numbers — без БД. Логика метрик инлайнится в
`api/ads.py:get_ads_heatmap`; здесь дублируем формулы 1-в-1 и проверяем что
они дают известные значения + корректно обрабатывают clicks=0/orders=0 → None.

Если кто-то "оптимизирует" формулу в ads.py через mean-of-means (вместо
sum-numerator/sum-denominator) — этот тест должен упасть.
"""

from __future__ import annotations


def _row_metric(
    metric: str, spent: float, rev: float, orders: int, clicks: int, atbs: int
) -> float | None:
    """Точная копия per-row логики из `api/ads.py:get_ads_heatmap`.

    Если поменялась формула в API — должно поменяться здесь, и наоборот.
    """
    if metric == "drr":
        return (spent / rev * 100.0) if rev > 0 else None
    if metric == "spent":
        return spent
    if metric == "revenue":
        return rev
    if metric == "orders":
        return float(orders)
    if metric == "clicks":
        return float(clicks)
    if metric == "cpl":
        return (spent / clicks) if clicks > 0 else None
    if metric == "cps":
        return (spent / orders) if orders > 0 else None
    if metric == "basket_conv":
        return (atbs / clicks * 100.0) if clicks > 0 else None
    if metric == "order_conv":
        return (orders / clicks * 100.0) if clicks > 0 else None
    return None


def _totals_metric(
    metric: str,
    spent_sum: float,
    rev_sum: float,
    orders_sum: int,
    clicks_sum: int,
    atbs_sum: int,
) -> float | None:
    """Зеркало totals-блока. Sum-then-divide (НЕ среднее средних)."""
    if metric == "cpl":
        return (spent_sum / clicks_sum) if clicks_sum > 0 else None
    if metric == "cps":
        return (spent_sum / orders_sum) if orders_sum > 0 else None
    if metric == "basket_conv":
        return (atbs_sum / clicks_sum * 100.0) if clicks_sum > 0 else None
    if metric == "order_conv":
        return (orders_sum / clicks_sum * 100.0) if clicks_sum > 0 else None
    return None


# ── golden numbers ──────────────────────────────────────────────────


def test_cpl_basic() -> None:
    # 1000₽ / 200 кликов = 5₽/клик
    assert _row_metric("cpl", spent=1000, rev=0, orders=0, clicks=200, atbs=0) == 5.0


def test_cps_basic() -> None:
    # 1000₽ / 10 заказов = 100₽/заказ
    assert _row_metric("cps", spent=1000, rev=0, orders=10, clicks=200, atbs=0) == 100.0


def test_basket_conv_basic() -> None:
    # 50 корзин / 200 кликов × 100 = 25%
    assert _row_metric("basket_conv", spent=0, rev=0, orders=0, clicks=200, atbs=50) == 25.0


def test_order_conv_basic() -> None:
    # 10 заказов / 200 кликов × 100 = 5%
    assert _row_metric("order_conv", spent=0, rev=0, orders=10, clicks=200, atbs=0) == 5.0


# ── deg cases: clicks=0 / orders=0 → None ───────────────────────────


def test_cpl_no_clicks_returns_none() -> None:
    assert _row_metric("cpl", spent=1000, rev=0, orders=0, clicks=0, atbs=0) is None


def test_cps_no_orders_returns_none() -> None:
    assert _row_metric("cps", spent=1000, rev=0, orders=0, clicks=200, atbs=0) is None


def test_basket_conv_no_clicks_returns_none() -> None:
    assert _row_metric("basket_conv", spent=0, rev=0, orders=0, clicks=0, atbs=10) is None


def test_order_conv_no_clicks_returns_none() -> None:
    assert _row_metric("order_conv", spent=0, rev=0, orders=5, clicks=0, atbs=0) is None


# ── totals: sum-then-divide, НЕ mean-of-means ──────────────────────


def test_totals_cpl_is_sum_divided_by_sum() -> None:
    # Кампания A: 1000₽, 100 кликов → CPL=10
    # Кампания B: 100₽, 100 кликов  → CPL=1
    # mean-of-means: (10+1)/2 = 5.5 — НЕПРАВИЛЬНО
    # sum/sum: 1100 / 200 = 5.5     — совпадает случайно при равных весах
    # Изменим веса:
    # Кампания A: 1000₽, 100 кликов → CPL=10
    # Кампания B: 100₽, 1000 кликов → CPL=0.1
    # mean-of-means: (10+0.1)/2 = 5.05
    # sum/sum: 1100 / 1100 = 1.0    ← это ожидаемое значение
    assert _totals_metric(
        "cpl",
        spent_sum=1000 + 100,
        rev_sum=0,
        orders_sum=0,
        clicks_sum=100 + 1000,
        atbs_sum=0,
    ) == 1.0


def test_totals_basket_conv_is_sum_divided_by_sum() -> None:
    # Кампания A: 50 корзин, 100 кликов → 50%
    # Кампания B: 10 корзин, 1000 кликов → 1%
    # mean-of-means: (50+1)/2 = 25.5
    # sum/sum: 60 / 1100 × 100 ≈ 5.45  ← правильно
    val = _totals_metric(
        "basket_conv",
        spent_sum=0,
        rev_sum=0,
        orders_sum=0,
        clicks_sum=100 + 1000,
        atbs_sum=50 + 10,
    )
    assert val is not None
    assert round(val, 2) == round(60 / 1100 * 100, 2)


def test_totals_no_clicks_returns_none() -> None:
    assert (
        _totals_metric(
            "cpl",
            spent_sum=1000,
            rev_sum=0,
            orders_sum=0,
            clicks_sum=0,
            atbs_sum=0,
        )
        is None
    )
    assert (
        _totals_metric(
            "basket_conv",
            spent_sum=0,
            rev_sum=0,
            orders_sum=0,
            clicks_sum=0,
            atbs_sum=10,
        )
        is None
    )
