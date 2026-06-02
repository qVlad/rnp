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
    debug_nomenclatures_raw,
    get_promotion_details,
    get_promotion_nomenclatures,
    list_active_promotions,
    probe_nomenclatures_params,
)
from app.services.auth import (
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.promo_calculator import (
    PromoSimulationInput,
    compare_promos_for_skus,
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


def _normalize_nomenclatures(
    items: list[dict[str, Any]], in_action: bool
) -> list[dict[str, Any]]:
    """Нормализует WB nomenclature-item'ы в форму, которую ждёт фронт:
    ``{nmID, inAction, price, discountedPrice}``.

    BUG-DEV-020: WB не отдаёт флаг `inAction` внутри item'а — тегируем по тому,
    каким запросом получили. Толерантно достаём nmID (`id`/`nmID`/`nmId`) и
    цены либо с верхнего уровня, либо из первого размера `sizes[]` (WB иногда
    кладёт price/discountedPrice именно туда).
    """

    def _num(v: Any) -> float:
        try:
            n = float(v)
            return n if n >= 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    out: list[dict[str, Any]] = []
    for n in items or []:
        if not isinstance(n, dict):
            continue
        nm = n.get("id") or n.get("nmID") or n.get("nmId") or n.get("nmid") or 0
        price = n.get("price")
        # BUG-DEV-020: реальная акционная цена WB — это `planPrice`
        # (см. дока nomenclatures), а не `discountedPrice`. Fallback на старые
        # имена для совместимости.
        disc = (
            n.get("planPrice")
            if n.get("planPrice") is not None
            else n.get("discountedPrice")
        )
        if (price is None or disc is None) and isinstance(n.get("sizes"), list):
            for sz in n["sizes"]:
                if not isinstance(sz, dict):
                    continue
                if price is None and sz.get("price") is not None:
                    price = sz.get("price")
                if disc is None and sz.get("discountedPrice") is not None:
                    disc = sz.get("discountedPrice")
                if price is not None and disc is not None:
                    break
        out.append(
            {
                "nmID": int(nm) if nm else 0,
                "inAction": in_action,
                "price": _num(price),
                "discountedPrice": _num(disc),
            }
        )
    return out


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
    debug: int = Query(0, description="BUG-DEV-020: 1=сырой ответ WB, 2=+probe"),
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
    details_obj = details[0] if details else None

    # BUG-DEV-020: по офиц. доке WB endpoint nomenclatures «Not applicable for
    # auto promotions» — для автоакций он всегда отдаёт 422. Поэтому для
    # `type:"auto"` НЕ дёргаем его (экономим вызовы + не мусорим в логи), а
    # отдаём флаг `auto_promo` — фронт показывает manual-ввод SKU.
    is_auto = isinstance(details_obj, dict) and details_obj.get("type") == "auto"
    if is_auto:
        nomenclatures: list[dict[str, Any]] = []
    else:
        # WB требует обязательный `inAction` — зовём дважды (предложенные +
        # участвующие) и тегируем каждый nm (WB не кладёт inAction в item).
        suggested = await get_promotion_nomenclatures(
            token, promotion_id, in_action=False
        )
        participating = await get_promotion_nomenclatures(
            token, promotion_id, in_action=True
        )
        nomenclatures = _normalize_nomenclatures(
            suggested, False
        ) + _normalize_nomenclatures(participating, True)
    out: dict[str, Any] = {
        "promotion_id": promotion_id,
        "details": details_obj,
        "nomenclatures": nomenclatures,
        "auto_promo": is_auto,
    }
    if debug >= 1:
        # BUG-DEV-020: сырой ответ WB (debug=1) + probe перебора (debug=2, медленнее).
        out["debug"] = {
            "suggested": await debug_nomenclatures_raw(
                token, promotion_id, in_action=False
            ),
            "participating": await debug_nomenclatures_raw(
                token, promotion_id, in_action=True
            ),
        }
        if debug >= 2:
            out["debug"]["probe"] = await probe_nomenclatures_params(
                token, promotion_id
            )
    return out


class ComparePromoMeta(BaseModel):
    """Одна акция-столбец для матрицы сравнения (TASK-DEV-030)."""

    id: int
    name: str | None = None
    start: str | None = None
    end: str | None = None
    # Ручной override скидки % — если задан, цена считается как
    # baseline×(1−disc), иначе берётся реальная WB-цена (discountedPrice).
    discount_override_pct: float | None = Field(default=None, ge=0, le=99)


class CompareRequest(BaseModel):
    promotions: list[ComparePromoMeta] = Field(..., min_length=1, max_length=6)
    baseline_period_days: conint(ge=1, le=90) = 14  # type: ignore


@router.post("/compare")
async def compare_promotions_endpoint(
    body: CompareRequest,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Матрица «текущие продажи vs N акций» по per-unit марже (TASK-DEV-030).

    Для каждой акции тянем nomenclatures (предложенные + участвующие) → цена по
    SKU = WB discountedPrice (или baseline×(1−override) если задан override %).
    Строки = объединение всех SKU акций (с baseline-продажами).
    """
    token = await _resolve_wb_token(session, user.tenant_id)
    promotions: list[dict[str, Any]] = []
    for meta in body.promotions:
        suggested = await get_promotion_nomenclatures(token, meta.id, in_action=False)
        participating = await get_promotion_nomenclatures(
            token, meta.id, in_action=True
        )
        norm = _normalize_nomenclatures(suggested, False) + _normalize_nomenclatures(
            participating, True
        )
        sku_price: dict[int, float] = {}
        for n in norm:
            nm = int(n.get("nmID") or 0)
            dp = n.get("discountedPrice") or n.get("price") or 0
            if nm and dp:
                # если nm встречается и как предложенный, и как участвующий —
                # берём первую (обычно совпадают по цене).
                sku_price.setdefault(nm, float(dp))
        promotions.append(
            {
                "id": meta.id,
                "name": meta.name or f"Акция {meta.id}",
                "start": meta.start,
                "end": meta.end,
                "sku_price": sku_price,
            }
        )

    overrides = {
        m.id: float(m.discount_override_pct)
        for m in body.promotions
        if m.discount_override_pct is not None
    }
    return await compare_promos_for_skus(
        session,
        promotions=promotions,
        overrides=overrides,
        baseline_period_days=int(body.baseline_period_days),
        brands=brands,
    )


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
    # TASK-DEV-031: реальные акционные цены WB по nm (planPrice). Если задано —
    # скидка считается per-SKU из цены, иначе единый discount_pct.
    promo_prices: dict[int, float] | None = None


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
        promo_prices=body.promo_prices,
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
