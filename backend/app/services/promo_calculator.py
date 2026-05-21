"""Калькулятор рентабельности WB-акций.

TASK-LEAD-050. Бизнес-вопрос: «WB предложил акцию −25% на 7 дней, ожидаемый
boost продаж +80% — выгодно ли вступать?»

Логика (pure-function):

1. **Baseline** (для каждого `nm_id`): за последние N дней посчитать
   средний дневной выкуп, выручку, цену, маржу per unit. Источник —
   `wb_report_detail` (canonical revenue/payout per-SKU).

2. **With promo:**
   - new_price = baseline_price × (1 − discount_pct/100)
   - new_velocity = baseline_velocity × (1 + velocity_boost_pct/100)
   - new_revenue_per_day = new_price × new_velocity × buyout_rate
   - new_margin_per_unit = new_price − cogs − commission_rate × new_price
                          − logistics_per_unit − storage_per_unit
   - new_total_margin = new_margin_per_unit × new_velocity × duration_days
                        × buyout_rate

3. **Сравнение:** revenue delta, margin delta, profitable yes/no.

4. **Breakeven boost:** минимальный velocity_boost при котором
   new_total_margin = baseline_margin_total. Если даже при boost=500%
   убыток — отдаём `None` (бессмысленно вступать).

Pure-функция `simulate_promo` принимает baseline-данные dict'ом — это
удобно для тестирования (можно подменить baseline) и для повторного
расчёта на frontend'е без нового запроса в БД.

Wrapper `simulate_promo_for_skus` сам подтягивает baseline из БД и
дёргает pure-функцию для каждого SKU.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cogs, Product, WbReportDetail
from app.services.period_aggregates import OP_RETURN, OP_SALE, REVENUE_FIELD


# Cap на breakeven-search — если при boost=500% всё ещё убыток,
# смысла искать дальше нет (нереалистично для любой акции).
_BREAKEVEN_MAX_BOOST_PCT = 500.0
_BREAKEVEN_SEARCH_STEP_PCT = 0.5


@dataclass(frozen=True)
class PromoSimulationInput:
    """Параметры симуляции акции (приходят с фронта)."""

    nm_ids: list[int]
    discount_pct: Decimal  # 0..100, скидка от текущей цены
    duration_days: int  # 1..60, сколько дней длится акция
    expected_velocity_boost_pct: Decimal  # 0..500, ожидаемый рост продаж
    baseline_period_days: int = 14  # 7/14/30, окно для расчёта baseline


@dataclass(frozen=True)
class SkuBaseline:
    """Baseline-метрики SKU за окно `baseline_period_days`.

    Все per-day величины — средние за окно (revenue/units/...) / days_in_window.
    """

    nm_id: int
    vendor_code: str | None
    brand: str | None
    photo_url: str | None
    days_in_window: int
    units_sold: int  # net (sale − return) за окно
    revenue_per_day: float  # canonical revenue (rev_sale − rev_return) / days
    velocity_per_day: float  # units_sold / days
    avg_price: float  # revenue_per_unit (учитывает текущие скидки/промо)
    buyout_rate: float  # 0..1 (если orders < sales — берём 1.0 как safe default)
    margin_per_unit: float  # avg_price − cogs − commission − logistics_per_unit
    commission_rate: float  # 0..1, calculated from rd_metrics
    logistics_per_unit: float  # delivery+storage+penalty распределённый per unit
    cogs_per_unit: float  # last known cogs


@dataclass(frozen=True)
class PromoSimulationResult:
    """Результат симуляции для одного SKU.

    Все per-day / per-unit / total — float (rounded в UI).
    """

    nm_id: int
    vendor_code: str | None
    brand: str | None
    photo_url: str | None
    baseline: dict[str, float]
    with_promo: dict[str, float]
    delta_pct: dict[str, float | None]  # None если baseline=0 (нельзя посчитать %)
    delta_abs: dict[str, float]
    is_profitable: bool  # total_margin_with_promo > 0
    is_better_than_baseline: bool  # total_margin_with_promo > baseline_total_margin
    breakeven_velocity_boost_pct: float | None  # None если недостижим в пределах cap


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def simulate_promo(
    baseline: SkuBaseline,
    *,
    discount_pct: float,
    duration_days: int,
    expected_velocity_boost_pct: float,
) -> PromoSimulationResult:
    """Pure-функция: baseline + параметры акции → симулированный исход.

    Не делает запросов в БД — все данные приходят через `baseline`.
    Это позволяет:
    - юнит-тестировать без БД (см. test_promo_calculator.py)
    - пересчитывать на frontend'е при изменении ползунка без round-trip
      (если когда-нибудь захотим WASM-сборку)

    Math:
    - new_price = avg_price × (1 − discount/100)
    - new_velocity = velocity_per_day × (1 + boost/100)
    - new_units_per_day = new_velocity × buyout_rate  (buyout_rate
      уже отражает фактический выкуп; cap'ируем на 1.0)
    - new_revenue_per_day = new_price × new_units_per_day
    - commission на новой цене: commission_rate (как доля от revenue)
      остаётся той же, abs = commission_rate × new_price
    - new_margin_per_unit = new_price − cogs − commission_per_unit
                            − logistics_per_unit
    - new_margin_total = new_margin_per_unit × new_units_per_day × duration_days

    Sanity: discount_pct cap'ируется в 0..99, boost cap'ируется в 0..1000
    (без верхней границы вообще даст бесконечный «прибыльно»).
    """
    discount_pct = max(0.0, min(99.0, float(discount_pct)))
    boost_pct = max(0.0, min(1000.0, float(expected_velocity_boost_pct)))
    duration_days = max(1, int(duration_days))

    # Baseline
    bl_price = baseline.avg_price
    bl_velocity = baseline.velocity_per_day
    bl_buyout = max(0.01, min(1.0, baseline.buyout_rate))  # avoid 0-div / >1
    bl_units_per_day = bl_velocity  # velocity уже NET (buyout-учтённый sales)
    bl_revenue_per_day = bl_units_per_day * bl_price
    bl_margin_per_unit = baseline.margin_per_unit
    bl_margin_per_day = bl_margin_per_unit * bl_units_per_day
    bl_revenue_total = bl_revenue_per_day * duration_days
    bl_margin_total = bl_margin_per_day * duration_days

    # With promo
    new_price = bl_price * (1.0 - discount_pct / 100.0)
    new_velocity = bl_velocity * (1.0 + boost_pct / 100.0)
    new_units_per_day = new_velocity  # boost применяется к net-velocity
    new_revenue_per_day = new_units_per_day * new_price
    # commission_rate уже «нормирован» на revenue — сохраняем долю
    commission_per_unit_new = baseline.commission_rate * new_price
    new_margin_per_unit = (
        new_price
        - baseline.cogs_per_unit
        - commission_per_unit_new
        - baseline.logistics_per_unit
    )
    new_margin_per_day = new_margin_per_unit * new_units_per_day
    new_revenue_total = new_revenue_per_day * duration_days
    new_margin_total = new_margin_per_day * duration_days

    # Deltas
    def _delta_pct(b: float, n: float) -> float | None:
        if abs(b) < 1e-9:
            return None
        return (n - b) / abs(b) * 100.0

    is_profitable = new_margin_per_unit > 0
    is_better_than_baseline = new_margin_total > bl_margin_total

    # Breakeven velocity boost: минимальный boost при котором
    # new_margin_total >= bl_margin_total. Линейный поиск по шагу 0.5%.
    breakeven: float | None = None
    if new_margin_per_unit > 0:
        # Чтобы маржа с акцией ≥ маржи без акции:
        #   new_margin_per_unit × bl_velocity × (1 + boost/100) × duration
        #     ≥ bl_margin_per_unit × bl_velocity × duration
        # ⇒ (1 + boost/100) ≥ bl_margin_per_unit / new_margin_per_unit
        # ⇒ boost_pct ≥ 100 × (bl_margin_per_unit / new_margin_per_unit − 1)
        # (требует new_margin_per_unit > 0 — иначе маржа всегда отрицательная
        # независимо от velocity; breakeven недостижим)
        if abs(new_margin_per_unit) > 1e-9 and bl_margin_per_unit > 0:
            ratio = bl_margin_per_unit / new_margin_per_unit
            be = (ratio - 1.0) * 100.0
            if be <= _BREAKEVEN_MAX_BOOST_PCT:
                breakeven = max(0.0, be)
        elif bl_margin_per_unit <= 0:
            # baseline сам по себе нерентабельный — любой boost > 0 уже
            # «лучше чем ничего», если new_margin_per_unit > 0.
            breakeven = 0.0

    baseline_dict = {
        "avg_price": round(bl_price, 2),
        "velocity_per_day": round(bl_velocity, 3),
        "buyout_rate": round(bl_buyout, 3),
        "revenue_per_day": round(bl_revenue_per_day, 2),
        "margin_per_unit": round(bl_margin_per_unit, 2),
        "margin_per_day": round(bl_margin_per_day, 2),
        "revenue_total": round(bl_revenue_total, 2),
        "margin_total": round(bl_margin_total, 2),
        "commission_rate_pct": round(baseline.commission_rate * 100, 2),
        "cogs_per_unit": round(baseline.cogs_per_unit, 2),
        "logistics_per_unit": round(baseline.logistics_per_unit, 2),
    }
    with_promo_dict = {
        "avg_price": round(new_price, 2),
        "velocity_per_day": round(new_velocity, 3),
        "buyout_rate": round(bl_buyout, 3),
        "revenue_per_day": round(new_revenue_per_day, 2),
        "margin_per_unit": round(new_margin_per_unit, 2),
        "margin_per_day": round(new_margin_per_day, 2),
        "revenue_total": round(new_revenue_total, 2),
        "margin_total": round(new_margin_total, 2),
        "commission_rate_pct": round(baseline.commission_rate * 100, 2),
        "cogs_per_unit": round(baseline.cogs_per_unit, 2),
        "logistics_per_unit": round(baseline.logistics_per_unit, 2),
    }
    delta_pct = {
        "revenue_per_day": _delta_pct(bl_revenue_per_day, new_revenue_per_day),
        "margin_per_unit": _delta_pct(bl_margin_per_unit, new_margin_per_unit),
        "margin_total": _delta_pct(bl_margin_total, new_margin_total),
        "revenue_total": _delta_pct(bl_revenue_total, new_revenue_total),
    }
    delta_abs = {
        "revenue_per_day": round(new_revenue_per_day - bl_revenue_per_day, 2),
        "margin_per_unit": round(new_margin_per_unit - bl_margin_per_unit, 2),
        "margin_total": round(new_margin_total - bl_margin_total, 2),
        "revenue_total": round(new_revenue_total - bl_revenue_total, 2),
    }

    return PromoSimulationResult(
        nm_id=baseline.nm_id,
        vendor_code=baseline.vendor_code,
        brand=baseline.brand,
        photo_url=baseline.photo_url,
        baseline=baseline_dict,
        with_promo=with_promo_dict,
        delta_pct=delta_pct,
        delta_abs=delta_abs,
        is_profitable=is_profitable,
        is_better_than_baseline=is_better_than_baseline,
        breakeven_velocity_boost_pct=(
            round(breakeven, 1) if breakeven is not None else None
        ),
    )


async def _load_baselines(
    session: AsyncSession,
    *,
    nm_ids: list[int],
    baseline_period_days: int,
    brands: set[str] | None = None,
) -> dict[int, SkuBaseline]:
    """Загрузить baseline для списка SKU из wb_report_detail + products + cogs.

    Источник выручки — canonical (см. period_aggregates):
        revenue_net = SUM(retail_price_withdisc_rub on Продажа)
                    − SUM(retail_price_withdisc_rub on Возврат)
    Units net = SUM(1 on Продажа) − SUM(1 on Возврат).
    Commission rate = (revenue_sale − ppvz_sale) / revenue_sale.
    """
    if not nm_ids:
        return {}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=baseline_period_days)

    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            func.coalesce(
                func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)), 0
            ).label("rev_sale"),
            func.coalesce(
                func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0)), 0
            ).label("rev_return"),
            func.coalesce(
                func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0)), 0
            ).label("ppvz_sale"),
            func.coalesce(
                func.sum(case((OP_SALE, 1), else_=0)), 0
            ).label("units_sale"),
            func.coalesce(
                func.sum(case((OP_RETURN, 1), else_=0)), 0
            ).label("units_return"),
            func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("delivery"),
            func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
            func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
        )
        .where(
            WbReportDetail.sale_dt >= start,
            WbReportDetail.sale_dt < end,
            WbReportDetail.nm_id.in_(nm_ids),
        )
        .group_by(WbReportDetail.nm_id)
    )
    rd_rows = (await session.execute(rd_stmt)).all()
    rd_by_nm: dict[int, Any] = {int(r.nm_id): r for r in rd_rows}

    # Products (vendor_code, brand, photo_url) — для UI.
    prod_stmt = select(Product).where(Product.nm_id.in_(nm_ids))
    if brands is not None:
        prod_stmt = prod_stmt.where(Product.brand.in_(list(brands)))
    prod_rows = (await session.execute(prod_stmt)).scalars().all()
    prods = {p.nm_id: p for p in prod_rows}

    # Latest cogs per nm.
    cogs_stmt = (
        select(Cogs.nm_id, Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
        .where(Cogs.nm_id.in_(nm_ids))
        .order_by(Cogs.nm_id, Cogs.valid_from.desc())
    )
    cogs_rows = (await session.execute(cogs_stmt)).all()
    cogs_by_nm: dict[int, float] = {}
    for r in cogs_rows:
        nm = int(r.nm_id)
        if nm in cogs_by_nm:
            continue
        cogs_by_nm[nm] = _f(r.cost_rub) + _f(r.packaging_rub) + _f(r.fulfillment_rub)

    out: dict[int, SkuBaseline] = {}
    for nm in nm_ids:
        prod = prods.get(nm)
        if prod is None:
            # Brand-scope: SKU не в whitelist'е → пропускаем (manager не видит).
            continue
        rd = rd_by_nm.get(nm)
        rev_sale = _f(rd.rev_sale) if rd else 0.0
        rev_return = _f(rd.rev_return) if rd else 0.0
        revenue_net = rev_sale - rev_return
        ppvz_sale = _f(rd.ppvz_sale) if rd else 0.0
        units_sale = int(rd.units_sale) if rd else 0
        units_return = int(rd.units_return) if rd else 0
        units_net = max(0, units_sale - units_return)
        delivery = _f(rd.delivery) if rd else 0.0
        storage = _f(rd.storage) if rd else 0.0
        penalty = _f(rd.penalty) if rd else 0.0

        # Avg price — выручка с учётом текущей скидки / unit (как продаёт WB).
        # Считаем по gross-sales (без возвратов), т.к. возврат не отражает
        # actual selling price.
        avg_price = rev_sale / units_sale if units_sale > 0 else 0.0

        # Commission rate как доля от revenue (Продажа only):
        #   (rev_sale − ppvz_sale) / rev_sale = WB-комиссия + acquiring
        commission_rate = (
            (rev_sale - ppvz_sale) / rev_sale if rev_sale > 0 else 0.0
        )
        commission_rate = max(0.0, min(0.95, commission_rate))  # sanity cap

        # Logistics per unit (delivery + storage + penalty / NET units).
        # NET, потому что storage платится 1 раз вне зависимости от
        # возврата, но distribute'ить лучше по фактически проданным.
        logistics_per_unit = (
            (delivery + storage + penalty) / units_net if units_net > 0 else 0.0
        )

        velocity_per_day = units_net / baseline_period_days
        revenue_per_day = revenue_net / baseline_period_days

        cogs_per_unit = cogs_by_nm.get(nm, 0.0)
        commission_per_unit = commission_rate * avg_price
        margin_per_unit = (
            avg_price - cogs_per_unit - commission_per_unit - logistics_per_unit
        )

        # buyout_rate: примерно units_net / (units_sale + units_return) (Inversed).
        # Если данных нет — 1.0 (conservative default: считаем что весь заказ выкупится).
        # Точная цифра из WbOrder не критична здесь — velocity уже NET.
        buyout_rate = 1.0

        out[nm] = SkuBaseline(
            nm_id=nm,
            vendor_code=prod.vendor_code,
            brand=prod.brand,
            photo_url=prod.photo_url,
            days_in_window=baseline_period_days,
            units_sold=units_net,
            revenue_per_day=revenue_per_day,
            velocity_per_day=velocity_per_day,
            avg_price=avg_price,
            buyout_rate=buyout_rate,
            margin_per_unit=margin_per_unit,
            commission_rate=commission_rate,
            logistics_per_unit=logistics_per_unit,
            cogs_per_unit=cogs_per_unit,
        )
    return out


async def simulate_promo_for_skus(
    session: AsyncSession,
    payload: PromoSimulationInput,
    *,
    brands: set[str] | None = None,
) -> list[PromoSimulationResult]:
    """High-level wrapper: загружает baseline из БД и считает симуляцию
    для каждого SKU.

    `brands` (если задан) — RBAC manager-фильтр. SKU вне whitelist'а
    отфильтровывается (не попадает в результат, не 403).
    """
    nm_ids = list(dict.fromkeys(payload.nm_ids))  # dedupe, сохранить порядок
    baselines = await _load_baselines(
        session,
        nm_ids=nm_ids,
        baseline_period_days=payload.baseline_period_days,
        brands=brands,
    )
    results: list[PromoSimulationResult] = []
    for nm in nm_ids:
        bl = baselines.get(nm)
        if bl is None:
            continue
        results.append(
            simulate_promo(
                bl,
                discount_pct=float(payload.discount_pct),
                duration_days=payload.duration_days,
                expected_velocity_boost_pct=float(payload.expected_velocity_boost_pct),
            )
        )
    return results


__all__ = [
    "PromoSimulationInput",
    "PromoSimulationResult",
    "SkuBaseline",
    "simulate_promo",
    "simulate_promo_for_skus",
]
