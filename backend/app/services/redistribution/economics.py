"""ROI-расчёты для модуля перераспределения.

Главный дифференциатор продукта vs конкурентов (QuotaBot/WBCON/Eggheads):
честный ROI в рублях. См. REDISTRIBUTION_PLAN §6.7.

Формула net_benefit на одну рекомендацию:

    cost_share = qty × marginal_fee_per_unit
    logistics_saving = (long_haul - short_haul_to_target) × demand_14d_at_target
    revenue_uplift = demand × price × IL_CONVERSION_UPLIFT
    net = logistics_saving + revenue_uplift - cost_share

Все коэффициенты — стартовые. Калибруются через 30-60 дней реальной работы
сравнением фактической выручки/логистики vs прогноза (см. §11 метрики).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


# Доля комиссии +0.5% от стоимости каждой единицы товара (по средней цене SKU).
# При оборотe 5М₽/мес и средней цене 2000₽: 2500 ед × 0.5% × 2000 ≈ 25k/мес.
# Marginal_fee_per_unit для расчёта на этот ROI = price × 0.005.
REDISTRIBUTION_FEE_RATE: Final = Decimal("0.005")

# Расходы на логистику WB зависят от расстояния «склад приёмки → склад покупателя».
# Если товар на «дальнем» складе и часто идёт в Москву — это +X₽ на ед.
# Стартовое ориентирное значение: 40₽ × 0.5 (50% заказов идёт «дальше»).
DEFAULT_LONG_HAUL_RUB_PER_UNIT: Final = Decimal("40")
DEFAULT_SHORT_HAUL_RUB_PER_UNIT: Final = Decimal("15")

# Уплифт выручки при росте ИЛ. На MVP — оценка 10-15% (если ИЛ растёт с 30%
# до 65%, ожидаем что выручка на этом SKU поднимется на ~12%).
# Калибровать после 60 дней работы через A/B сравнение.
IL_CONVERSION_UPLIFT: Final = Decimal("0.10")

# Минимальный лот по правилам WB — 5 ед. Меньше не пройдёт.
MIN_LOT: Final = 5


@dataclass
class Economics:
    """Чистый разрез ROI для одной рекомендации."""

    qty: int
    expected_logistics_saving_rub: Decimal
    expected_revenue_uplift_rub: Decimal
    cost_share_rub: Decimal
    net_benefit_rub: Decimal
    payback_days: Decimal | None  # дней до окупаемости комиссии за этот SKU


def compute_economics(
    *,
    qty: int,
    avg_price_rub: Decimal,
    demand_14d: int,
    long_haul_rub_per_unit: Decimal = DEFAULT_LONG_HAUL_RUB_PER_UNIT,
    short_haul_rub_per_unit: Decimal = DEFAULT_SHORT_HAUL_RUB_PER_UNIT,
    il_uplift_factor: Decimal = IL_CONVERSION_UPLIFT,
    fee_rate: Decimal = REDISTRIBUTION_FEE_RATE,
) -> Economics:
    """Считает ROI на одну рекомендацию (один chrt_id × один склад).

    Все аргументы — keyword-only, чтобы избежать путаницы порядка.
    Возвращает Economics с net_benefit_rub (может быть отрицательным).
    """
    qty_d = Decimal(qty)
    cost_share = qty_d * avg_price_rub * fee_rate
    logistics_diff = long_haul_rub_per_unit - short_haul_rub_per_unit
    logistics_saving = logistics_diff * Decimal(demand_14d)
    revenue_uplift = Decimal(demand_14d) * avg_price_rub * il_uplift_factor
    net = logistics_saving + revenue_uplift - cost_share

    # payback: сколько дней нужно, чтобы экономия+uplift отбили комиссию.
    # Daily_benefit = (logistics_saving + revenue_uplift) / 14
    payback: Decimal | None
    daily_benefit = (logistics_saving + revenue_uplift) / Decimal(14)
    if daily_benefit > 0:
        payback = cost_share / daily_benefit
    else:
        payback = None

    return Economics(
        qty=qty,
        expected_logistics_saving_rub=logistics_saving.quantize(Decimal("0.01")),
        expected_revenue_uplift_rub=revenue_uplift.quantize(Decimal("0.01")),
        cost_share_rub=cost_share.quantize(Decimal("0.01")),
        net_benefit_rub=net.quantize(Decimal("0.01")),
        payback_days=payback.quantize(Decimal("0.1")) if payback else None,
    )
