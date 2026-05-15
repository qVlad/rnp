"""Джем — поисковая аналитика: кластеризация запросов + MAX-границы.

Алгоритм:
  1. Берём jam_queries для nm_id за период.
  2. Кластеризуем по «корню» — самое частое слово ≥3 символов в запросе.
     Например: "платье красное", "платье синее" → кластер "платье".
  3. Для каждого кластера агрегируем orders/clicks/views/ad_spent.
  4. Считаем CTR, CPC, конверсии корзина→заказ.
  5. MAX-границы (CPC, корзина, заказ) — через UnitEconomics SKU + organic.

Цветовая разметка статуса (для UI):
  green   — CPC < 70% MAX_CPC (с маржой)
  yellow  — CPC 70-100% MAX_CPC (на границе)
  red     — CPC > MAX_CPC (убыток)
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cogs, JamQuery, Product


# ── Кластеризация ─────────────────────────────────────────────────────

# Стоп-слова которые игнорируем как «ядро» кластера
_STOPWORDS = {
    "для", "на", "из", "под", "над", "при", "от", "до", "по", "в", "и",
    "с", "к", "не", "или", "за", "что", "это", "как", "так",
    "the", "a", "an", "of", "in", "for", "with",
}

_WORD_RE = re.compile(r"[a-zа-яё0-9]{3,}", re.IGNORECASE)


def _normalize(s: str) -> str:
    return s.strip().lower()


def _tokens(query: str) -> list[str]:
    return [
        t.lower() for t in _WORD_RE.findall(query.lower()) if t.lower() not in _STOPWORDS
    ]


def _cluster_key(query: str, global_freq: dict[str, int]) -> str:
    """Корень кластера = самое частое слово (по global_freq) из токенов запроса.

    Если слов нет — кластер «прочее»."""
    toks = _tokens(query)
    if not toks:
        return "прочее"
    # Из этих токенов выбираем тот что встречается в global_freq чаще всего
    best = max(toks, key=lambda t: global_freq.get(t, 0))
    return best


# ── Агрегация и расчёт ────────────────────────────────────────────────


@dataclass
class ClusterRow:
    cluster: str
    queries: list[str]
    orders: int = 0
    clicks: int = 0
    views: int = 0
    ad_spent: float = 0.0


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def _get_sku_unit_economics(
    session: AsyncSession, nm_id: int
) -> dict[str, float]:
    """Достаёт минимально необходимые параметры юнит-экономики SKU для MAX-расчёта.

    Возвращает {price, cogs, commission_pct, acquiring_pct, logistics_per_unit,
    buyout_pct, marketing_per_unit}. Если данных мало — возвращает оценки.
    """
    # Цена и комиссия — из последнего wb_report_detail для SKU (упрощённо).
    from app.db.models import WbReportDetail
    from sqlalchemy import case, func
    from app.services.period_aggregates import OP_SALE, REVENUE_FIELD

    # Берём последние 30 дней
    cutoff_dt = date.today() - timedelta(days=30)
    rd_stmt = (
        select(
            func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)).label("rev"),
            func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0)).label("ppvz"),
            func.sum(case((OP_SALE, 1), else_=0)).label("units"),
            func.sum(WbReportDetail.delivery_rub).label("delivery"),
        )
        .where(WbReportDetail.nm_id == nm_id)
        .where(WbReportDetail.rr_dt >= cutoff_dt)
    )
    row = (await session.execute(rd_stmt)).one()
    units = int(row.units or 0)
    rev = _f(row.rev)
    ppvz = _f(row.ppvz)
    delivery = _f(row.delivery)
    avg_price = rev / units if units > 0 else 0.0
    commission_pct = ((rev - ppvz) / rev * 100.0) if rev > 0 else 18.0
    logistics_per_unit = (delivery / units) if units > 0 else 80.0

    # COGS
    cogs_row = (
        await session.execute(
            select(Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
            .where(Cogs.nm_id == nm_id, Cogs.valid_from <= date.today())
            .order_by(Cogs.valid_from.desc())
            .limit(1)
        )
    ).one_or_none()
    cogs_unit = (
        _f(cogs_row.cost_rub) + _f(cogs_row.packaging_rub) + _f(cogs_row.fulfillment_rub)
        if cogs_row
        else 0.0
    )

    return {
        "price": avg_price,
        "cogs": cogs_unit,
        "commission_pct": round(commission_pct, 2),
        "acquiring_pct": 1.5,
        "logistics_per_unit": round(logistics_per_unit, 2),
        "buyout_pct": 80.0,  # дефолт; уточнить из реальных продаж в будущем
        "units_30d": units,
        "revenue_30d": rev,
    }


def _max_cpc_for(
    *,
    price: float,
    cogs: float,
    commission_pct: float,
    acquiring_pct: float,
    logistics_per_unit: float,
    organic_pct: float,
    cart_conversion_pct: float,
    order_conversion_pct: float,
    target_margin_pct: float = 0.0,
) -> dict[str, float]:
    """Простая повторная имплементация max-расчёта из frontend calc.ts.
    Возвращает {max_per_order, max_cpc, max_basket, max_order, max_buyout}."""
    if price <= 0:
        return {
            "max_per_order": 0.0,
            "max_cpc": 0.0,
            "max_basket": 0.0,
            "max_order": 0.0,
            "max_buyout": 0.0,
        }
    wb_commission = price * commission_pct / 100.0
    acquiring = price * acquiring_pct / 100.0
    logistics_eff = logistics_per_unit  # упрощено: без поправки на выкуп
    expenses_wo_marketing = wb_commission + acquiring + logistics_eff + cogs
    target_margin = price * target_margin_pct / 100.0
    max_per_order = max(0.0, price - expenses_wo_marketing - target_margin)
    organic = max(0.0, min(100.0, organic_pct)) / 100.0
    paid_share = max(0.01, 1.0 - organic)
    max_per_paid_order = max_per_order / paid_share
    cart_conv = max(0.0, min(100.0, cart_conversion_pct)) / 100.0
    order_conv = max(0.0, min(100.0, order_conversion_pct)) / 100.0
    max_buyout = max_per_order * 0.8  # × buyout (упрощено 80%)
    max_order = max_per_paid_order
    max_basket = max_order * order_conv if order_conv > 0 else 0.0
    max_cpc = (max_basket * cart_conv) if cart_conv > 0 and max_basket > 0 else 0.0
    return {
        "max_per_order": round(max_per_order, 2),
        "max_cpc": round(max_cpc, 2),
        "max_basket": round(max_basket, 2),
        "max_order": round(max_order, 2),
        "max_buyout": round(max_buyout, 2),
    }


def _status_for(cpc: float, max_cpc: float) -> str:
    """10X-разметка: красный > MAX, жёлтый 70-100% MAX (включая границы), зелёный < 70%."""
    if max_cpc <= 0:
        return "ok"
    ratio = cpc / max_cpc
    if ratio > 1.0:
        return "red"
    if ratio >= 0.7:
        return "yellow"
    return "green"


async def build_jam_clusters(
    session: AsyncSession,
    *,
    nm_id: int,
    days_back: int = 30,
    organic_pct: float = 0.0,
    target_margin_pct: float = 0.0,
) -> dict[str, Any]:
    """Кластеризованные запросы для SKU за период."""
    end = date.today()
    start = end - timedelta(days=days_back)

    product = (
        await session.execute(select(Product).where(Product.nm_id == nm_id))
    ).scalar_one_or_none()
    if product is None:
        return {"nm_id": nm_id, "found": False, "clusters": []}

    rows = (
        await session.execute(
            select(JamQuery).where(
                JamQuery.nm_id == nm_id,
                JamQuery.period_start >= start,
            )
        )
    ).scalars().all()

    if not rows:
        ue = await _get_sku_unit_economics(session, nm_id)
        return {
            "nm_id": nm_id,
            "found": True,
            "vendor_code": product.vendor_code,
            "brand": product.brand,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "clusters": [],
            "unit_economics": ue,
            "message": (
                "Нет загруженных запросов. Добавьте через Excel-импорт "
                "(/settings → Excel I/O → jam_queries) или дождитесь WB Jam-синхронизации."
            ),
        }

    # Глобальная частота слов (для определения «ядра» кластера)
    global_freq: Counter[str] = Counter()
    for r in rows:
        for t in _tokens(r.query):
            global_freq[t] += 1

    # Группировка
    clusters: dict[str, ClusterRow] = {}
    for r in rows:
        key = _cluster_key(r.query, global_freq)
        cl = clusters.setdefault(key, ClusterRow(cluster=key, queries=[]))
        cl.queries.append(r.query)
        cl.orders += int(r.orders or 0)
        cl.clicks += int(r.clicks or 0)
        cl.views += int(r.views or 0)
        cl.ad_spent += _f(r.ad_spent)

    # Юнит-экономика SKU (для MAX-границ)
    ue = await _get_sku_unit_economics(session, nm_id)

    out_clusters: list[dict[str, Any]] = []
    for cl in sorted(clusters.values(), key=lambda x: -x.orders):
        avg_cart_conv = (cl.orders / cl.clicks * 100.0) if cl.clicks > 0 else 0.0
        avg_order_conv = 100.0  # уже только заказы — упрощённо
        ctr = (cl.clicks / cl.views * 100.0) if cl.views > 0 else 0.0
        cpc = (cl.ad_spent / cl.clicks) if cl.clicks > 0 else 0.0
        drr = (cl.ad_spent / (cl.orders * ue["price"]) * 100.0) if cl.orders > 0 and ue["price"] > 0 else 0.0
        max_metrics = _max_cpc_for(
            price=ue["price"],
            cogs=ue["cogs"],
            commission_pct=ue["commission_pct"],
            acquiring_pct=ue["acquiring_pct"],
            logistics_per_unit=ue["logistics_per_unit"],
            organic_pct=organic_pct,
            cart_conversion_pct=avg_cart_conv,
            order_conversion_pct=avg_order_conv,
            target_margin_pct=target_margin_pct,
        )
        status = _status_for(cpc, max_metrics["max_cpc"])
        out_clusters.append(
            {
                "cluster": cl.cluster,
                "queries_count": len(cl.queries),
                "queries_sample": cl.queries[:5],
                "orders": cl.orders,
                "clicks": cl.clicks,
                "views": cl.views,
                "ctr": round(ctr, 2),
                "cart_conv_pct": round(avg_cart_conv, 2),
                "order_conv_pct": round(avg_order_conv, 2),
                "ad_spent": round(cl.ad_spent, 2),
                "cpc": round(cpc, 2),
                "drr": round(drr, 2),
                "max_cpc": max_metrics["max_cpc"],
                "max_basket": max_metrics["max_basket"],
                "max_order": max_metrics["max_order"],
                "max_per_order": max_metrics["max_per_order"],
                "status": status,
            }
        )

    return {
        "nm_id": nm_id,
        "found": True,
        "vendor_code": product.vendor_code,
        "brand": product.brand,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "unit_economics": ue,
        "clusters": out_clusters,
        "totals": {
            "queries_total": sum(c["queries_count"] for c in out_clusters),
            "orders_total": sum(c["orders"] for c in out_clusters),
            "clusters_total": len(out_clusters),
            "red_clusters": sum(1 for c in out_clusters if c["status"] == "red"),
            "yellow_clusters": sum(1 for c in out_clusters if c["status"] == "yellow"),
        },
    }


async def upsert_jam_query(
    session: AsyncSession,
    *,
    nm_id: int,
    query: str,
    period_start: date,
    period_end: date,
    orders: int = 0,
    clicks: int = 0,
    views: int = 0,
    ad_spent: float = 0.0,
) -> JamQuery:
    """Добавить или обновить запись поискового запроса. Уникальный ключ —
    (tenant, nm_id, query, period_start)."""
    existing = (
        await session.execute(
            select(JamQuery).where(
                JamQuery.nm_id == nm_id,
                JamQuery.query == query,
                JamQuery.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.period_end = period_end
        existing.orders = orders
        existing.clicks = clicks
        existing.views = views
        existing.ad_spent = Decimal(str(ad_spent))
        return existing
    obj = JamQuery(
        nm_id=nm_id,
        query=query,
        period_start=period_start,
        period_end=period_end,
        orders=orders,
        clicks=clicks,
        views=views,
        ad_spent=Decimal(str(ad_spent)),
    )
    session.add(obj)
    return obj
