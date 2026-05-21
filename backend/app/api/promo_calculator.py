"""API endpoint для калькулятора рентабельности WB-акций (TASK-LEAD-050).

`POST /api/promo-calculator/simulate` — симулирует impact акции
(скидка% × N дней × ожидаемый boost) на маржу / выручку SKU.

Brand-filter через `current_brands_filter` — manager видит только
nm_id из своего whitelist'а. SKU вне whitelist'а просто пропускаются
(не 403 — возможно манагер выбрал смешанный набор, частичный результат
полезнее ошибки).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, conint, condecimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db  # noqa: F401  (used by get_db_tenant_scoped)
from app.services.auth import current_brands_filter, get_db_tenant_scoped
from app.services.promo_calculator import (
    PromoSimulationInput,
    simulate_promo_for_skus,
)

router = APIRouter(prefix="/api/promo-calculator", tags=["promo-calculator"])


class SimulateRequest(BaseModel):
    """Параметры симуляции акции.

    discount_pct: 0..99 (100 = бесплатная раздача — нет бизнес-смысла).
    duration_days: 1..60 (WB-акции редко длятся дольше месяца).
    expected_velocity_boost_pct: 0..500 — пользовательский ползунок,
        подсказка «в среднем WB-акции дают +50..150%».
    baseline_period_days: 7/14/30 — окно для расчёта baseline-velocity.
    """

    nm_ids: list[int] = Field(..., min_length=1, max_length=200)
    discount_pct: condecimal(ge=Decimal("0"), le=Decimal("99")) = Decimal("25")  # type: ignore
    duration_days: conint(ge=1, le=60) = 7  # type: ignore
    expected_velocity_boost_pct: condecimal(ge=Decimal("0"), le=Decimal("500")) = Decimal("80")  # type: ignore
    baseline_period_days: conint(ge=1, le=90) = 14  # type: ignore


@router.post("/simulate")
async def simulate_promo_endpoint(
    body: SimulateRequest,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Симуляция акции для списка SKU.

    Returns:
        {
            "params": { discount_pct, duration_days, ... },  # echo + canonical
            "items": [PromoSimulationResult.dict_repr() ...],
            "totals": {
                "skipped_nm_ids": [ ... ],  # не найдены/вне brand scope
                "profitable_count": int,
                "better_than_baseline_count": int,
                "sum_baseline_margin_total": float,
                "sum_with_promo_margin_total": float,
                "sum_baseline_revenue_total": float,
                "sum_with_promo_revenue_total": float,
            },
        }
    """
    payload = PromoSimulationInput(
        nm_ids=body.nm_ids,
        discount_pct=Decimal(body.discount_pct),
        duration_days=int(body.duration_days),
        expected_velocity_boost_pct=Decimal(body.expected_velocity_boost_pct),
        baseline_period_days=int(body.baseline_period_days),
    )
    results = await simulate_promo_for_skus(session, payload, brands=brands)

    returned_nm_ids = {r.nm_id for r in results}
    skipped = [nm for nm in body.nm_ids if nm not in returned_nm_ids]

    items: list[dict[str, Any]] = []
    sum_bl_rev = 0.0
    sum_bl_margin = 0.0
    sum_new_rev = 0.0
    sum_new_margin = 0.0
    profitable_count = 0
    better_count = 0
    for r in results:
        items.append({
            "nm_id": r.nm_id,
            "vendor_code": r.vendor_code,
            "brand": r.brand,
            "photo_url": r.photo_url,
            "baseline": r.baseline,
            "with_promo": r.with_promo,
            "delta_pct": r.delta_pct,
            "delta_abs": r.delta_abs,
            "is_profitable": r.is_profitable,
            "is_better_than_baseline": r.is_better_than_baseline,
            "breakeven_velocity_boost_pct": r.breakeven_velocity_boost_pct,
        })
        sum_bl_rev += r.baseline.get("revenue_total", 0.0)
        sum_bl_margin += r.baseline.get("margin_total", 0.0)
        sum_new_rev += r.with_promo.get("revenue_total", 0.0)
        sum_new_margin += r.with_promo.get("margin_total", 0.0)
        if r.is_profitable:
            profitable_count += 1
        if r.is_better_than_baseline:
            better_count += 1

    return {
        "params": {
            "nm_ids": body.nm_ids,
            "discount_pct": float(body.discount_pct),
            "duration_days": int(body.duration_days),
            "expected_velocity_boost_pct": float(body.expected_velocity_boost_pct),
            "baseline_period_days": int(body.baseline_period_days),
        },
        "items": items,
        "totals": {
            "skipped_nm_ids": skipped,
            "items_count": len(items),
            "profitable_count": profitable_count,
            "better_than_baseline_count": better_count,
            "sum_baseline_revenue_total": round(sum_bl_rev, 2),
            "sum_baseline_margin_total": round(sum_bl_margin, 2),
            "sum_with_promo_revenue_total": round(sum_new_rev, 2),
            "sum_with_promo_margin_total": round(sum_new_margin, 2),
            "sum_delta_revenue_total": round(sum_new_rev - sum_bl_rev, 2),
            "sum_delta_margin_total": round(sum_new_margin - sum_bl_margin, 2),
        },
    }
