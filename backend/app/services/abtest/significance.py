"""Статистика значимости для A/B-тестов.

Порт `wbab/src/lib/stats/significance.ts` 1:1 на Python:
- двусторонний Z-test для пропорций (CTR и CR как бинарные конверсии)
- Wilson score interval для CI (устойчив на малых выборках)
- порог значимости: p < 0.05

Никаких I/O — чистые функции, безопасно вызывать из API-хендлеров,
Celery-task'ов, тестов.

Отличие от TS-оригинала: вместо аппроксимации Абрамовица-Стегуна используем
`math.erf` — в стандартной библиотеке, точнее на ±5σ.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "ZTestResult",
    "WilsonCI",
    "VariantStats",
    "SignificanceReport",
    "TopMetric",
    "TopDenom",
    "z_test",
    "wilson_ci",
    "compute_significance",
]


def _norm_cdf(z: float) -> float:
    """Стандартное нормальное CDF через erf — точнее A&S-аппроксимации."""
    if z < -8.0:
        return 0.0
    if z > 8.0:
        return 1.0
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass
class ZTestResult:
    p_value: float
    z_score: float
    significant: bool
    alpha: float


def z_test(
    success_a: int,
    n_a: int,
    success_b: int,
    n_b: int,
    alpha: float = 0.05,
) -> ZTestResult:
    """Двусторонний Z-test для двух независимых пропорций.

    Args:
        success_a: число успехов (кликов/заказов) у варианта A
        n_a: число испытаний (показов/кликов) у варианта A
        success_b: число успехов у варианта B
        n_b: число испытаний у варианта B
        alpha: уровень значимости (default 0.05)
    """
    if n_a == 0 or n_b == 0:
        return ZTestResult(p_value=1.0, z_score=0.0, significant=False, alpha=alpha)

    p_a = success_a / n_a
    p_b = success_b / n_b
    pooled = (success_a + success_b) / (n_a + n_b)

    # Стандартная ошибка при H0 (p_a == p_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        # Все одинаково: либо 0/0, либо 1/1. p_a == p_b → p=1; иначе p=0.
        return ZTestResult(
            p_value=1.0 if p_a == p_b else 0.0,
            z_score=0.0,
            significant=p_a != p_b,
            alpha=alpha,
        )

    z = (p_a - p_b) / se
    # Двусторонний: умножаем хвост на 2.
    p_value = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return ZTestResult(
        p_value=p_value,
        z_score=z,
        significant=p_value < alpha,
        alpha=alpha,
    )


@dataclass
class WilsonCI:
    lower: float
    upper: float
    center: float


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> WilsonCI:
    """Доверительный интервал Уилсона. Точнее Wald-CI при малых p и n."""
    if n == 0:
        return WilsonCI(lower=0.0, upper=0.0, center=0.0)

    # z для двустороннего CI при уровне (1-alpha): z = Φ^-1(1 - alpha/2)
    # 3 типичные точки — хватает; промежуточные не нужны.
    z_alpha = 1.96 if alpha <= 0.05 else (1.645 if alpha <= 0.1 else 1.28)
    z2 = z_alpha * z_alpha
    p = successes / n

    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    margin = (z_alpha / (1 + z2 / n)) * math.sqrt(
        (p * (1 - p)) / n + z2 / (4 * n * n)
    )
    return WilsonCI(
        center=center,
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


# Какое поле использовать в качестве числителя «верхней метрики» воронки:
#   "clicks"   → clicks
#   "cartAdds" → cartAdds
TopMetric = Literal["clicks", "cartAdds"]

# Какое поле использовать в качестве знаменателя «верхней метрики» воронки:
#   "impressions" → impressions
#   "clicks"      → clicks (для adv: «дошёл до карточки через клик»)
#
# Правильные сочетания (по change_logic wbab):
#   ADV_ONLY + PHOTO   → top=clicks,   denom=impressions  (показ → клик)
#   ANY + FUNNEL       → top=cartAdds, denom=impressions  (открытие → корзина)
#   BOTH + FUNNEL      → как ANY+FUNNEL (winnerSource=nm-report)
#   ADV_ONLY + FUNNEL  → top=cartAdds, denom=clicks       (клик → корзина)
TopDenom = Literal["impressions", "clicks"]


@dataclass
class VariantStats:
    """Сырая статистика варианта для одного теста."""

    variant_id: int
    label: str
    impressions: int
    clicks: int
    cart_adds: int
    orders: int
    # Опционально — если CSV-репорт DETAIL_HISTORY_REPORT успел синкнуться.
    buyouts: int | None = None


@dataclass
class VariantRate:
    rate: float
    ci: WilsonCI


@dataclass
class PairwiseTest:
    a_label: str
    b_label: str
    a_id: int
    b_id: int
    ctr_test: ZTestResult
    cr_test: ZTestResult


@dataclass
class WinnerInfo:
    variant_id: int
    label: str


@dataclass
class SampleProgress:
    variant_id: int
    label: str
    current: int
    target: int
    pct: int  # 0..100


@dataclass
class SignificanceReport:
    # variant_id → rate + CI
    ctr: dict[int, VariantRate]
    cr: dict[int, VariantRate]
    pairwise: list[PairwiseTest]
    # Победитель по верхней метрике (CTR/CR) — только при значимом результате.
    ctr_winner: WinnerInfo | None
    cr_winner: WinnerInfo | None
    sample_progress: list[SampleProgress]


def compute_significance(
    variants: list[VariantStats],
    min_sample_size: int,
    alpha: float = 0.05,
    top_metric: TopMetric = "clicks",
    top_denom: TopDenom = "impressions",
) -> SignificanceReport:
    """Полный отчёт о значимости для набора вариантов теста.

    Поля `ctr` исторически называются «CTR», но физически это «верхняя
    метрика воронки» — её числитель управляется параметром `top_metric`:
    для PHOTO-тестов на adv-источнике это `clicks` (классический CTR),
    для FUNNEL-тестов это `cart_adds` (показ → корзина).

    Поле `cr` — «вторая метрика», `orders / top_metric`. После change_logic
    в победителе НЕ используется, показывается справочно.

    sample_progress всегда считается по `impressions` — это объём данных,
    независимо от того, по какой формуле определяется победитель.
    """

    def top_field(v: VariantStats) -> int:
        return v.cart_adds if top_metric == "cartAdds" else v.clicks

    def denom_field(v: VariantStats) -> int:
        return v.clicks if top_denom == "clicks" else v.impressions

    ctr: dict[int, VariantRate] = {}
    cr: dict[int, VariantRate] = {}

    for v in variants:
        top = top_field(v)
        denom = denom_field(v)
        ctr[v.variant_id] = VariantRate(
            rate=(top / denom) if denom > 0 else 0.0,
            ci=wilson_ci(top, denom, alpha),
        )
        cr[v.variant_id] = VariantRate(
            rate=(v.orders / top) if top > 0 else 0.0,
            ci=wilson_ci(v.orders, top, alpha),
        )

    # Все попарные тесты (N выбор 2)
    pairwise: list[PairwiseTest] = []
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            a = variants[i]
            b = variants[j]
            top_a = top_field(a)
            top_b = top_field(b)
            denom_a = denom_field(a)
            denom_b = denom_field(b)
            pairwise.append(
                PairwiseTest(
                    a_id=a.variant_id,
                    b_id=b.variant_id,
                    a_label=a.label,
                    b_label=b.label,
                    ctr_test=z_test(top_a, denom_a, top_b, denom_b, alpha),
                    cr_test=z_test(a.orders, top_a, b.orders, top_b, alpha),
                )
            )

    # Победителя объявляем только если ВСЕ варианты набрали min_sample_size
    # (sample = impressions, объём входа).
    all_sampled = all(v.impressions >= min_sample_size for v in variants)

    ctr_winner: WinnerInfo | None = None
    cr_winner: WinnerInfo | None = None

    if all_sampled and len(variants) == 2 and len(pairwise) == 1:
        pair = pairwise[0]
        a, b = variants[0], variants[1]

        if pair.ctr_test.significant:
            denom_a = denom_field(a)
            denom_b = denom_field(b)
            rate_a = (top_field(a) / denom_a) if denom_a > 0 else 0.0
            rate_b = (top_field(b) / denom_b) if denom_b > 0 else 0.0
            winner = a if rate_a >= rate_b else b
            ctr_winner = WinnerInfo(variant_id=winner.variant_id, label=winner.label)

        if pair.cr_test.significant:
            top_a = top_field(a)
            top_b = top_field(b)
            rate_a = (a.orders / top_a) if top_a > 0 else 0.0
            rate_b = (b.orders / top_b) if top_b > 0 else 0.0
            winner = a if rate_a >= rate_b else b
            cr_winner = WinnerInfo(variant_id=winner.variant_id, label=winner.label)

    elif all_sampled and len(variants) > 2:
        # При N > 2: победитель — тот, кто значимо лучше ВСЕХ остальных по
        # верхней метрике.
        rated = []
        for v in variants:
            denom = denom_field(v)
            rated.append((v, (top_field(v) / denom) if denom > 0 else 0.0))
        rated.sort(key=lambda x: x[1], reverse=True)
        best_v = rated[0][0]
        best_wins_all = all(
            p.ctr_test.significant
            for p in pairwise
            if p.a_id == best_v.variant_id or p.b_id == best_v.variant_id
        )
        if best_wins_all:
            ctr_winner = WinnerInfo(variant_id=best_v.variant_id, label=best_v.label)

    sample_progress = [
        SampleProgress(
            variant_id=v.variant_id,
            label=v.label,
            current=v.impressions,
            target=min_sample_size,
            pct=min(100, round((v.impressions / min_sample_size) * 100))
            if min_sample_size > 0
            else 0,
        )
        for v in variants
    ]

    return SignificanceReport(
        ctr=ctr,
        cr=cr,
        pairwise=pairwise,
        ctr_winner=ctr_winner,
        cr_winner=cr_winner,
        sample_progress=sample_progress,
    )
