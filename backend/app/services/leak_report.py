"""Leak-report — «найдено N₽» аудит-артефакт (TASK-LEAD-140).

Агрегирует по периоду все места, где у селлера утекают или зависают деньги,
в одно число `total_found_rub` + breakdown по категориям. Используется как
ритуал входа в клуб (онбординг кабинета) и sales-артефакт для предпродажи.

**Recon — не источник суммы, а badge доверия** «✅ сверено с WB-кабинетом
до рубля»: показываем, сколько недель совпали в пределах 1%.

Категории (`kind`):
  - `recover`  — деньги, которые можно вернуть (оспорить штрафы/чарджбэки)
  - `prevent`  — потери/переплаты, которые можно прекратить (минусовые SKU,
                 дохлый сток в платном хранении, переплата логистики из-за
                 перемеров WB, убыточные акции)

Все денежные источники переиспользуют существующие сервисы, чтобы не
расходиться с дашбордом:
  - `services.unit_economics.build_unit_economics` — per-SKU маржа + сток + хранение
  - `services.chargebacks` — оспоримые штрафы
  - `services.pnl_reconciliation.build_reconciliation` — trust-badge
  - `WbProductDimensionsHistory` × `WbTariffBox` — перемеры → Δ логистики
  - `wb_report_detail` (seller_promo_*) — ретро-оценка убыточных акций
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chargeback,
    Cogs,
    Product,
    WbProductDimensionsHistory,
    WbReportDetail,
    WbTariffBox,
)
from app.services.chargebacks import CATEGORY_LABELS, INCOME_CATEGORIES
from app.services.pnl_reconciliation import build_reconciliation

# Категории чарджбэков, которые НЕ идут в «оспоримые / вернуть» (TASK-LEAD-142):
#   - damage_compensation  — «Компенсация ущерба»: деньги В ПОЛЬЗУ селлера
#     (WB возмещает нам за порчу), это доход, а не штраф к возврату.
#   - voluntary_compensation — «Добровольная компенсация при возврате»: селлер
#     согласился сам → оспорить нельзя (и это его расход, не возвратный).
NON_RECOVERABLE_CATEGORIES = set(INCOME_CATEGORIES) | {"voluntary_compensation"}

# Реально ОСПОРИМЫЕ категории → идут в «найдено» (group=found). Штраф + явные
# коррекции, где у претензии есть шанс.
DISPUTABLE_CATEGORIES = {
    "penalty",
    "delivery_correction",
    "sale_correction",
    "acquiring_correction",
    "loyalty_correction",
}
# Прочие удержания → блок «разобрать» (group=review), НЕ суммируются в «найдено»:
# generic «Удержание» в массе легитимно, платная приёмка / хранение с низким ИЛ —
# это реальные сборы, а не возвратные деньги. Показываем, но не обещаем возврат.
REVIEW_CATEGORIES = {"deduction", "low_il_storage_fee", "paid_acceptance"}
from app.services.period_aggregates import OP_SALE
from app.services.unit_economics import build_unit_economics

log = logging.getLogger(__name__)


# Дохлый сток: продано ≤ этого числа штук за период, но платим хранение.
DEAD_STOCK_MAX_UNITS_SOLD = 0
# Сколько SKU показывать детально в каждой категории (для печатного отчёта).
TOP_SKU_LIMIT = 10
# Допуск изменения объёма (л) чтобы считать перемером — отсекаем округления.
VOLUME_CHANGE_TOLERANCE_L = 0.01


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _brand_nm_subq(brands: set[str] | None):
    """Подзапрос nm_id ограниченный брендами (None = без ограничения)."""
    if brands is None:
        return None
    return select(Product.nm_id).where(Product.brand.in_(list(brands)))


# ──────────────────────────────────────────────────────────────────────
# 1. Оспоримые штрафы / чарджбэки (recover)
# ──────────────────────────────────────────────────────────────────────
async def _chargebacks_split(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    brands: set[str] | None,
) -> dict[str, Any]:
    """Не-закрытые удержания/штрафы (status new/disputing), кроме income и
    добровольной компенсации, разбитые на два блока (TASK-LEAD-142):

    - `disputable` (→ «найдено»): штраф + явные коррекции, где претензия имеет
      шанс. Это `DISPUTABLE_CATEGORIES`.
    - `review` (→ «разобрать», НЕ суммируется в найдено): generic «Удержание»,
      платная приёмка, хранение с низким ИЛ — в массе легитимны, не возвратные.

    Сумма = amount_rub − recovered_amount (что ещё не вернули).
    """
    net_amount = Chargeback.amount_rub - func.coalesce(Chargeback.recovered_amount, 0)
    stmt = (
        select(
            Chargeback.category,
            func.coalesce(func.sum(net_amount), 0).label("amount"),
            func.count().label("cnt"),
        )
        .where(
            Chargeback.status.in_(("new", "disputing")),
            Chargeback.category.notin_(tuple(NON_RECOVERABLE_CATEGORIES)),
            Chargeback.operation_dt >= date_from,
            Chargeback.operation_dt <= date_to,
        )
        .group_by(Chargeback.category)
    )
    nm_subq = _brand_nm_subq(brands)
    if nm_subq is not None:
        # Для manager-scope берём только штрафы по своим SKU (nm_id IS NULL —
        # это общефирменные удержания, их видит только director).
        stmt = stmt.where(Chargeback.nm_id.in_(nm_subq))
    rows = (await session.execute(stmt)).all()

    def _bucket(categories: set[str]) -> dict[str, Any]:
        by_cat = [
            {
                "category": r.category,
                "label": CATEGORY_LABELS.get(r.category, r.category),
                "amount": round(_f(r.amount), 2),
                "count": int(r.cnt),
            }
            for r in rows
            if r.category in categories and _f(r.amount) > 0
        ]
        by_cat.sort(key=lambda x: x["amount"], reverse=True)
        return {
            "amount": round(sum(c["amount"] for c in by_cat), 2),
            "count": sum(c["count"] for c in by_cat),
            "by_category": by_cat,
        }

    return {
        "disputable": _bucket(DISPUTABLE_CATEGORIES),
        "review": _bucket(REVIEW_CATEGORIES),
    }


# ──────────────────────────────────────────────────────────────────────
# 2-3. Минусовые SKU + дохлый сток в хранении (prevent) — из unit-экономики
# ──────────────────────────────────────────────────────────────────────
def _negative_margin(items: list[dict[str, Any]]) -> dict[str, Any]:
    """SKU, реально проданные за период в убыток (net_profit < 0 И продажи > 0).

    BUG-DEV-018: требуем `units_sold_gross > 0`. Без этого SKU с 0 продаж,
    но платным хранением/рекламой, уходили в минус по net_profit и ложно
    попадали в «проданные в убыток» (0 шт) + их хранение дублировалось с
    блоком dead-stock. Теперь блоки disjoint: negative-margin = продано>0,
    dead-stock = продано=0 → нет двойного счёта.
    """
    losers = [
        it
        for it in items
        if _f(it.get("net_profit")) < 0
        and int(it.get("units_sold_gross", 0) or 0) > 0
    ]
    losers.sort(key=lambda it: _f(it.get("net_profit")))  # самый минусовой первым
    total = round(sum(-_f(it.get("net_profit")) for it in losers), 2)
    return {
        "amount": total,
        "count": len(losers),
        "top_skus": [
            {
                "nm_id": it["nm_id"],
                "vendor_code": it.get("vendor_code"),
                "brand": it.get("brand"),
                "photo_url": it.get("photo_url"),
                "loss": round(-_f(it.get("net_profit")), 2),
                "margin_pct": _f(it.get("margin_pct")),
                "units_sold": it.get("units_sold_gross", 0),
            }
            for it in losers[:TOP_SKU_LIMIT]
        ],
    }


def _dead_stock_storage(
    items: list[dict[str, Any]], cogs: dict[int, float]
) -> dict[str, Any]:
    """Платим хранение за сток, который не продаётся (units_sold_gross ≤ порог).

    Это НЕ чистая экономия (TASK-LEAD-142): чтобы прекратить, надо распродать
    (потеря маржи) либо вывезти/утилизировать (плата WB + логистика). Плюс в
    товаре заморожен капитал = stock × COGS. Поэтому отдаём и `storage` (что
    капает за период), и `frozen_capital` (сколько заморожено в товаре).
    """
    dead = [
        it
        for it in items
        if _f(it.get("storage")) > 0
        and _f(it.get("stock")) > 0
        and int(it.get("units_sold_gross", 0) or 0) <= DEAD_STOCK_MAX_UNITS_SOLD
    ]
    dead.sort(key=lambda it: _f(it.get("storage")), reverse=True)
    total = round(sum(_f(it.get("storage")) for it in dead), 2)
    frozen_capital = round(
        sum(
            int(it.get("stock", 0) or 0) * cogs.get(int(it["nm_id"]), 0.0)
            for it in dead
        ),
        2,
    )
    return {
        "amount": total,
        "frozen_capital": frozen_capital,
        "count": len(dead),
        "top_skus": [
            {
                "nm_id": it["nm_id"],
                "vendor_code": it.get("vendor_code"),
                "brand": it.get("brand"),
                "photo_url": it.get("photo_url"),
                "storage": round(_f(it.get("storage")), 2),
                "stock": int(it.get("stock", 0) or 0),
                "frozen_capital": round(
                    int(it.get("stock", 0) or 0) * cogs.get(int(it["nm_id"]), 0.0), 2
                ),
            }
            for it in dead[:TOP_SKU_LIMIT]
        ],
    }


# ──────────────────────────────────────────────────────────────────────
# 4. Перемеры WB → переплата логистики (prevent)
# ──────────────────────────────────────────────────────────────────────
async def _delivery_liter_lookup(session: AsyncSession) -> dict[str, float]:
    """Последний (по effective_from) delivery_liter на склад. Плюс ключ
    `__any__` — медиана/любой как fallback для складов без тарифа."""
    rows = (
        await session.execute(
            select(
                WbTariffBox.warehouse_name,
                WbTariffBox.delivery_liter,
                WbTariffBox.effective_from,
            ).order_by(WbTariffBox.warehouse_name, WbTariffBox.effective_from.desc())
        )
    ).all()
    out: dict[str, float] = {}
    for r in rows:
        wh = r.warehouse_name
        if wh in out:
            continue
        out[wh] = _f(r.delivery_liter)
    if out:
        out.setdefault("__any__", sorted(out.values())[len(out) // 2])  # медиана
    return out


async def _remeasure_logistics_overpay(
    session: AsyncSession,
    *,
    date_to: date,
    units_by_nm: dict[int, int],
    brands: set[str] | None,
) -> dict[str, Any]:
    """WB молча увеличил габариты → объём вырос → логистика дороже.

    Δ_per_unit = (volume_l − prev_volume_l) × delivery_liter(склад).
    overpay = Δ_per_unit × units_sold_gross (фактически отгружено за период).
    Берём только реальные увеличения объёма (change_kind='changed').
    """
    # Последний перемер на nm (DISTINCT ON), увеличивший объём, в силе на конец периода.
    end_dt = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    h = WbProductDimensionsHistory
    stmt = (
        select(
            h.nm_id,
            h.volume_l,
            h.prev_volume_l,
            h.detected_at,
        )
        .where(
            h.change_kind == "changed",
            h.detected_at < end_dt,
            h.volume_l.isnot(None),
            h.prev_volume_l.isnot(None),
            h.volume_l > h.prev_volume_l,
        )
        .distinct(h.nm_id)
        .order_by(h.nm_id, h.detected_at.desc())
    )
    nm_subq = _brand_nm_subq(brands)
    if nm_subq is not None:
        stmt = stmt.where(h.nm_id.in_(nm_subq))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {"amount": 0.0, "count": 0, "top_skus": []}

    # Склад по умолчанию на nm (для тарифа).
    wh_by_nm: dict[int, str | None] = {}
    prod_rows = (
        await session.execute(
            select(Product.nm_id, Product.warehouse_default, Product.vendor_code, Product.brand, Product.photo_url).where(
                Product.nm_id.in_([int(r.nm_id) for r in rows])
            )
        )
    ).all()
    prod_meta: dict[int, Any] = {}
    for p in prod_rows:
        wh_by_nm[int(p.nm_id)] = p.warehouse_default
        prod_meta[int(p.nm_id)] = p

    liter = await _delivery_liter_lookup(session)
    any_liter = liter.get("__any__", 0.0)

    skus: list[dict[str, Any]] = []
    for r in rows:
        nm = int(r.nm_id)
        units = int(units_by_nm.get(nm, 0))
        if units <= 0:
            continue  # перемер был, но за период ничего не отгрузили — деньги не текут
        dv = _f(r.volume_l) - _f(r.prev_volume_l)
        if dv < VOLUME_CHANGE_TOLERANCE_L:
            continue
        rate = liter.get(wh_by_nm.get(nm) or "", any_liter) or any_liter
        delta_per_unit = dv * rate
        overpay = delta_per_unit * units
        if overpay <= 0:
            continue
        meta = prod_meta.get(nm)
        skus.append(
            {
                "nm_id": nm,
                "vendor_code": getattr(meta, "vendor_code", None),
                "brand": getattr(meta, "brand", None),
                "photo_url": getattr(meta, "photo_url", None),
                "prev_volume_l": round(_f(r.prev_volume_l), 3),
                "volume_l": round(_f(r.volume_l), 3),
                "delta_per_unit": round(delta_per_unit, 2),
                "units_sold": units,
                "overpay": round(overpay, 2),
            }
        )
    skus.sort(key=lambda x: x["overpay"], reverse=True)
    total = round(sum(s["overpay"] for s in skus), 2)
    return {"amount": total, "count": len(skus), "top_skus": skus[:TOP_SKU_LIMIT]}


# ──────────────────────────────────────────────────────────────────────
# 5. Убыточные акции постфактум (prevent)
# ──────────────────────────────────────────────────────────────────────
async def _latest_cogs_per_unit(session: AsyncSession) -> dict[int, float]:
    rows = (
        await session.execute(
            select(
                Cogs.nm_id,
                Cogs.cost_rub,
                Cogs.packaging_rub,
                Cogs.fulfillment_rub,
                Cogs.valid_from,
            ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
        )
    ).all()
    out: dict[int, float] = {}
    for r in rows:
        nm = int(r.nm_id)
        if nm in out:
            continue
        out[nm] = _f(r.cost_rub) + _f(r.packaging_rub) + _f(r.fulfillment_rub)
    return out


async def _loss_making_promos(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    brands: set[str] | None,
    cogs: dict[int, float],
) -> dict[str, Any]:
    """Акционные продажи, ушедшие в минус после комиссии/логистики/COGS.

    Промо-строка = `seller_promo_id` задан ИЛИ `seller_promo`/
    `seller_promo_discount` > 0. На уровне nm считаем:
      promo_margin = Σppvz_for_pay − COGS×units − Σdelivery
    Если < 0 → этот SKU торговался на акции в убыток, loss = −promo_margin.
    """
    start_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    is_promo = or_(
        WbReportDetail.seller_promo_id.isnot(None),
        func.coalesce(WbReportDetail.seller_promo, 0) > 0,
        func.coalesce(WbReportDetail.seller_promo_discount, 0) > 0,
    )
    stmt = (
        select(
            WbReportDetail.nm_id,
            func.count().label("units"),
            func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0).label("ppvz"),
            func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("delivery"),
        )
        .where(
            OP_SALE,
            is_promo,
            WbReportDetail.nm_id.isnot(None),
            WbReportDetail.sale_dt >= start_dt,
            WbReportDetail.sale_dt < end_dt,
        )
        .group_by(WbReportDetail.nm_id)
    )
    nm_subq = _brand_nm_subq(brands)
    if nm_subq is not None:
        stmt = stmt.where(WbReportDetail.nm_id.in_(nm_subq))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {"amount": 0.0, "count": 0, "top_skus": []}

    meta_rows = (
        await session.execute(
            select(Product.nm_id, Product.vendor_code, Product.brand, Product.photo_url).where(
                Product.nm_id.in_([int(r.nm_id) for r in rows])
            )
        )
    ).all()
    meta = {int(m.nm_id): m for m in meta_rows}

    skus: list[dict[str, Any]] = []
    for r in rows:
        nm = int(r.nm_id)
        units = int(r.units or 0)
        ppvz = _f(r.ppvz)
        delivery = _f(r.delivery)
        promo_margin = ppvz - cogs.get(nm, 0.0) * units - delivery
        if promo_margin >= 0:
            continue
        m = meta.get(nm)
        skus.append(
            {
                "nm_id": nm,
                "vendor_code": getattr(m, "vendor_code", None),
                "brand": getattr(m, "brand", None),
                "photo_url": getattr(m, "photo_url", None),
                "promo_units": units,
                "promo_margin": round(promo_margin, 2),
                "loss": round(-promo_margin, 2),
            }
        )
    skus.sort(key=lambda x: x["loss"], reverse=True)
    total = round(sum(s["loss"] for s in skus), 2)
    return {"amount": total, "count": len(skus), "top_skus": skus[:TOP_SKU_LIMIT]}


# ──────────────────────────────────────────────────────────────────────
# Recon trust-badge
# ──────────────────────────────────────────────────────────────────────
async def _trust_badge(
    session: AsyncSession, *, brands: set[str] | None
) -> dict[str, Any]:
    """«✅ сверено с WB-кабинетом» — сколько недель совпали в пределах 1%."""
    try:
        recon = await build_reconciliation(session, weeks_back=12, brands=brands)
    except Exception as exc:  # noqa: BLE001 — badge не должен ронять весь отчёт
        log.warning("leak_report trust badge skipped: %s", exc)
        return {"available": False}
    periods = recon.get("periods", [])
    weeks_total = len(periods)
    weeks_matched = sum(1 for p in periods if not p.get("diff", {}).get("alert"))
    max_diff = max(
        (abs(_f(p.get("diff", {}).get("revenue_gross_pct"))) for p in periods),
        default=0.0,
    )
    return {
        "available": weeks_total > 0,
        "weeks_total": weeks_total,
        "weeks_matched": weeks_matched,
        "max_diff_pct": round(max_diff, 2),
    }


# ──────────────────────────────────────────────────────────────────────
# Главная сборка
# ──────────────────────────────────────────────────────────────────────
async def build_leak_report(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Собрать аудит-отчёт «найдено N₽» за период [date_from, date_to]."""
    # Один проход юнит-экономики покрывает источники 2-3 + даёт units_by_nm для #4.
    unit_econ = await build_unit_economics(
        session, start_date=date_from, end_date=date_to, brands=brands
    )
    items: list[dict[str, Any]] = unit_econ.get("items", [])
    units_by_nm = {
        int(it["nm_id"]): int(it.get("units_sold_gross", 0) or 0) for it in items
    }
    cogs = await _latest_cogs_per_unit(session)

    chargebacks = await _chargebacks_split(
        session, date_from=date_from, date_to=date_to, brands=brands
    )
    negative = _negative_margin(items)
    dead_stock = _dead_stock_storage(items, cogs)
    remeasure = await _remeasure_logistics_overpay(
        session, date_to=date_to, units_by_nm=units_by_nm, brands=brands
    )
    promos = await _loss_making_promos(
        session, date_from=date_from, date_to=date_to, brands=brands, cogs=cogs
    )
    badge = await _trust_badge(session, brands=brands)

    # ── 4 честных группы (TASK-LEAD-142) ─────────────────────────────────
    #   found  — деньги, которые реально вернуть / дёшево остановить
    #   review — удержания WB к разбору (в массе легитимны) — НЕ суммируем в found
    #   frozen — дохлый сток: хранение капает + капитал заморожен, действие
    #            (вывоз/распродажа/утилизация) тоже стоит денег → НЕ чистая экономия
    #   lost   — уже потеряно (убыточные акции постфактум), вернуть нельзя — урок
    breakdown = [
        {
            "leak_type": "disputable_chargebacks",
            "label": "Штрафы и коррекции WB — оспорить",
            "group": "found",
            "kind": "recover",
            "icon": "💰",
            "amount": chargebacks["disputable"]["amount"],
            "count": chargebacks["disputable"]["count"],
            "hint": (
                "Штраф + явные коррекции (логистика/продажи/эквайринг/лояльность) — "
                "по ним у претензии в WB есть шанс. Выигрыш не гарантирован."
            ),
            "details": chargebacks["disputable"]["by_category"],
        },
        {
            "leak_type": "review_deductions",
            "label": "Удержания WB — разобрать",
            "group": "review",
            "kind": "review",
            "icon": "🔍",
            "amount": chargebacks["review"]["amount"],
            "count": chargebacks["review"]["count"],
            "hint": (
                "Generic «Удержание», платная приёмка, хранение с низким ИЛ — "
                "в массе легитимны, не возвратные. Проверить спорные, но в «найдено» "
                "НЕ входит. «Компенсация ущерба» (доход) и «добровольная компенсация» "
                "(не оспаривается) сюда тоже не входят."
            ),
            "details": chargebacks["review"]["by_category"],
        },
        {
            "leak_type": "negative_margin_skus",
            "label": "SKU, проданные в убыток",
            "group": "found",
            "kind": "stop",
            "icon": "📉",
            "amount": negative["amount"],
            "count": negative["count"],
            "hint": "Реально проданы с отрицательной прибылью — поднять цену / срезать рекламу (действие почти бесплатное)",
            "details": negative["top_skus"],
        },
        {
            "leak_type": "remeasure_logistics",
            "label": "Переплата логистики из-за перемеров WB",
            "group": "found",
            "kind": "stop",
            "icon": "🔧",
            "amount": remeasure["amount"],
            "count": remeasure["count"],
            "hint": "WB увеличил габариты карточки — перепроверить замеры / оспорить",
            "details": remeasure["top_skus"],
        },
        {
            "leak_type": "dead_stock_storage",
            "label": "Хранение дохлого стока",
            "group": "frozen",
            "kind": "frozen",
            "icon": "📦",
            "amount": dead_stock["amount"],
            "frozen_capital": dead_stock["frozen_capital"],
            "count": dead_stock["count"],
            "hint": (
                "Хранение капает + в товаре заморожен капитал (сток×COGS). "
                "Прекратить = распродать (потеря маржи) либо вывезти/утилизировать "
                "(плата WB + логистика). Это НЕ чистая экономия, а сигнал разобраться."
            ),
            "details": dead_stock["top_skus"],
        },
        {
            "leak_type": "loss_making_promos",
            "label": "Убыточные акции (уже потеряно)",
            "group": "lost",
            "kind": "lost",
            "icon": "🏷️",
            "amount": promos["amount"],
            "count": promos["count"],
            "hint": "Эти SKU торговались на акции ниже себестоимости+логистики. Вернуть нельзя — урок на будущее.",
            "details": promos["top_skus"],
        },
    ]

    def _sum(group: str) -> float:
        return round(sum(b["amount"] for b in breakdown if b["group"] == group), 2)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "totals": {
            "found_rub": _sum("found"),
            "review_rub": _sum("review"),
            "frozen_rub": _sum("frozen"),
            "frozen_capital_rub": dead_stock["frozen_capital"],
            "lost_rub": _sum("lost"),
        },
        "trust_badge": badge,
        "breakdown": breakdown,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
