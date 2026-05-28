"""API endpoint для калькулятора рентабельности WB-акций (TASK-LEAD-050).

`POST /api/promo-calculator/simulate` — симулирует impact акции
(скидка% × N дней × ожидаемый boost) на маржу / выручку SKU.

Brand-filter через `current_brands_filter` — manager видит только
nm_id из своего whitelist'а. SKU вне whitelist'а просто пропускаются
(не 403 — возможно манагер выбрал смешанный набор, частичный результат
полезнее ошибки).

TASK-LEAD-155: добавлены GET endpoints для подгрузки актуальных WB-акций
из `dp-calendar-api.wildberries.ru` — отдельная страница UI с auto-fill.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, conint, condecimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.db.session import get_db  # noqa: F401  (used by get_db_tenant_scoped)
from app.integrations.wb.promotions import (
    get_promotion_details,
    get_promotion_nomenclatures,
    list_active_promotions,
)
from app.services.auth import (
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.promo_calculator import (
    PromoSimulationInput,
    simulate_promo_for_skus,
)
from app.services.secrets_crypto import decrypt

router = APIRouter(prefix="/api/promo-calculator", tags=["promo-calculator"])


async def _resolve_wb_token(session: AsyncSession, tenant_id: int) -> str:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.wb_token:
        raise HTTPException(400, "WB-токен не настроен — открой /settings")
    token = decrypt(tenant.wb_token) or ""
    if not token:
        raise HTTPException(400, "WB-токен не расшифровывается")
    return token


@router.get("/wb-promotions")
async def list_wb_promotions(
    start_date: date | None = Query(None, description="ISO YYYY-MM-DD"),
    end_date: date | None = Query(None, description="ISO YYYY-MM-DD"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Список WB-акций в окне дат.

    Источник: `GET dp-calendar-api/api/v1/calendar/promotions` (TASK-LEAD-155).
    По умолчанию — текущий день .. +90 дней. WB иногда возвращает 401/404 —
    тогда отдаём пустой список (graceful fallback).
    """
    token = await _resolve_wb_token(session, user.tenant_id)
    sd = start_date or date.today()
    ed = end_date or (sd + timedelta(days=90))
    promos = await list_active_promotions(
        token, start_date=sd, end_date=ed, include_all=True
    )
    return promos


@router.get("/wb-promotions/{promotion_id}")
async def get_wb_promotion(
    promotion_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Детали акции WB + список товаров (предложенных и участвующих).

    Объединяет два WB-эндпоинта `details` и `nomenclatures`. nm_id, по которым
    WB предлагает участвовать, — это поле `inAction=false`; уже участвующие —
    `inAction=true`. UI сам разделит/покажет toggle.
    """
    token = await _resolve_wb_token(session, user.tenant_id)
    details = await get_promotion_details(token, [promotion_id])
    nomenclatures = await get_promotion_nomenclatures(token, promotion_id)
    return {
        "promotion_id": promotion_id,
        "details": details[0] if details else None,
        "nomenclatures": nomenclatures,
    }


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
