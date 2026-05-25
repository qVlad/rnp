"""Локализация заказов — % заказов, отгружённых из склада в том же кластере,
что и регион покупателя (TASK-LEAD-052).

Бизнес-смысл: WB сам в кабинете «Аналитика → Локализация» показывает % заказов
которые отгружены **из склада ближайшего к покупателю**. Низкая локализация =
дальняя доставка = выше logistics_fee + удлинённый срок до клиента + ниже
конверсия (slow shipping → отказы / возвраты).

Источник данных: **`wb_orders`** (вариант A — миграция не нужна).
WB при синке `/api/v1/supplier/orders` отдаёт:
  - `warehouseName` → `wb_orders.warehouse_name` — откуда отгружено
  - `oblastOkrugName` → `wb_orders.oblast` — федеральный округ покупателя
  - `regionName` → `wb_orders.region_name` — регион (область) покупателя

Маппинг склад → кластер (7 округов РФ + INTL + OTHER) уже есть в
`services.clusters` — переиспользуем.

Локализация = склад_кластер == покупатель_кластер.
'OTHER'/'OTHER' тоже считаем НЕ локализованным (избегаем false-positive
от непокрытых imен в маппинге).

API:
    compute_localization(session, tenant_id, period_from, period_to, brands=None)
        → LocalizationStats(
            period_from, period_to,
            total_orders, localized_orders, localization_pct,
            by_cluster: list[ClusterLocalization],
            by_brand:   list[BrandLocalization],
            by_warehouse: list[WarehouseLocalization],
            worst_skus: list[SkuLocalization],
        )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbOrder
from app.services.clusters import (
    CLUSTER_LABELS,
    CLUSTER_ORDER,
    cluster_for_oblast,
    cluster_for_warehouse,
    cluster_label,
)


# --------------------------------------------------------------------------- #
# Result DTOs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClusterLocalization:
    cluster: str  # код кластера ЦФО/SFO/...
    cluster_label: str
    orders: int
    localized_orders: int
    localization_pct: float
    revenue: float  # total_price (для веса)


@dataclass(frozen=True)
class BrandLocalization:
    brand: str  # "" если неизвестен
    orders: int
    localized_orders: int
    localization_pct: float
    # TASK-LEAD-085: WoW в процентных пунктах.
    # localization_pct (current) − localization_pct (prev week).
    # None если за prev period нет данных или объём ниже порога
    # (бренд не был «представительным» в прошлой неделе).
    wow_pct: float | None = None


@dataclass(frozen=True)
class WarehouseLocalization:
    warehouse: str  # имя склада
    cluster: str
    cluster_label: str
    orders: int
    localized_orders: int
    localization_pct: float


@dataclass(frozen=True)
class SkuLocalization:
    nm_id: int
    vendor_code: str | None
    brand: str | None
    subject: str | None
    orders: int
    localized_orders: int
    localization_pct: float


@dataclass(frozen=True)
class LocalizationHeatmapCell:
    """Одна ячейка heatmap «склад × кластер покупателя»."""
    warehouse: str
    warehouse_cluster: str
    buyer_cluster: str
    orders: int


@dataclass(frozen=True)
class LocalizationStats:
    period_from: date
    period_to: date
    total_orders: int
    localized_orders: int
    localization_pct: float
    by_cluster: list[ClusterLocalization]
    by_brand: list[BrandLocalization]
    by_warehouse: list[WarehouseLocalization]
    worst_skus: list[SkuLocalization]
    heatmap: list[LocalizationHeatmapCell]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _safe_pct(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round(100.0 * numer / denom, 2)


def _to_dt_utc(d: date, *, end_of_day: bool = False) -> datetime:
    """Конверт date → tz-aware UTC datetime для сравнения с `order_dt`."""
    if end_of_day:
        return datetime.combine(d, time(23, 59, 59, 999000), tzinfo=timezone.utc)
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def is_localized(warehouse_name: str | None, oblast: str | None,
                 region_name: str | None) -> bool:
    """Локализован ли заказ.

    Localized := cluster(warehouse) == cluster(buyer). Если хотя бы один из
    кластеров 'OTHER' — НЕ локализован (нет уверенности в маппинге → не
    завышаем оценку).
    """
    wh_cluster = cluster_for_warehouse(warehouse_name)
    buyer_cluster = cluster_for_oblast(oblast, region_name)
    if wh_cluster == "OTHER" or buyer_cluster == "OTHER":
        return False
    return wh_cluster == buyer_cluster


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def _compute_brand_pct_map(
    session: AsyncSession,
    tenant_id: int,
    period_from: date,
    period_to: date,
    brands: list[str] | None,
    min_orders: int,
) -> dict[str, float]:
    """Posчитать map `brand → localization_pct` за прошлый период (для WoW).

    Используется отдельно от `compute_localization` чтобы не платить
    overhead полного breakdown'а (heatmap / worst_skus / by_warehouse) для
    окна-сравнения. Возвращает только бренды с `orders >= min_orders`
    (репрезентативные).
    """
    dt_from = _to_dt_utc(period_from)
    dt_to = _to_dt_utc(period_to, end_of_day=True)

    stmt = (
        select(
            WbOrder.warehouse_name,
            WbOrder.oblast,
            WbOrder.region_name,
            WbOrder.brand,
            Product.brand.label("p_brand"),
        )
        .join(Product, Product.nm_id == WbOrder.nm_id, isouter=True)
        .where(
            WbOrder.tenant_id == tenant_id,
            WbOrder.order_dt >= dt_from,
            WbOrder.order_dt <= dt_to,
            WbOrder.is_cancel.is_(False),
        )
    )
    if brands is not None:
        if not brands:
            return {}
        stmt = stmt.where(Product.brand.in_(brands))

    rows = (await session.execute(stmt)).all()

    buckets: dict[str, dict[str, int]] = {}
    for r in rows:
        wh_cluster = cluster_for_warehouse(r.warehouse_name)
        buyer_cluster = cluster_for_oblast(r.oblast, r.region_name)
        loc = (
            wh_cluster != "OTHER"
            and buyer_cluster != "OTHER"
            and wh_cluster == buyer_cluster
        )
        brand_key = (r.p_brand or r.brand or "").strip()
        b = buckets.setdefault(brand_key, {"orders": 0, "localized": 0})
        b["orders"] += 1
        if loc:
            b["localized"] += 1

    return {
        name: _safe_pct(b["localized"], b["orders"])
        for name, b in buckets.items()
        if b["orders"] >= min_orders
    }


async def compute_localization(
    session: AsyncSession,
    tenant_id: int,
    period_from: date,
    period_to: date,
    brands: Iterable[str] | None = None,
    worst_sku_limit: int = 10,
    brand_min_orders: int = 10,
) -> LocalizationStats:
    """Посчитать KPI локализации за период.

    Args:
        session: scoped session с `tenant_id` уже выставленным.
        tenant_id: для фильтрации `wb_orders.tenant_id` (defence in depth).
        period_from: включительно (UTC день).
        period_to: включительно (UTC день).
        brands: whitelist; None ⇒ все бренды.
        worst_sku_limit: топ-N SKU с самой низкой локализацией (только nm
            с >= 5 заказами, чтобы исключить статистический шум).
        brand_min_orders: TASK-LEAD-085, минимальный объём заказов чтобы
            бренд попал в `by_brand` (default 10). Отсекает статистический
            шум: бренды с 1-2 заказами дают «100% локализация» или «0%»
            что не несёт сигнала.

    Returns:
        LocalizationStats — KPI + breakdown'ы.
    """
    if period_to < period_from:
        period_from, period_to = period_to, period_from

    dt_from = _to_dt_utc(period_from)
    dt_to = _to_dt_utc(period_to, end_of_day=True)

    brand_list = list(brands) if brands is not None else None

    # Базовый SELECT с JOIN на products только для resolve бренда/subject.
    # WB при синке копирует `brand` прямо в `wb_orders.brand` — но это
    # legacy текст, который может отставать от справочника. Для brand-filter
    # надёжнее идти через `products` (там единая нормализация).
    stmt = (
        select(
            WbOrder.nm_id,
            WbOrder.warehouse_name,
            WbOrder.oblast,
            WbOrder.region_name,
            WbOrder.brand,
            WbOrder.is_cancel,
            WbOrder.total_price,
            Product.vendor_code,
            Product.brand.label("p_brand"),
            Product.subject.label("p_subject"),
        )
        .join(Product, Product.nm_id == WbOrder.nm_id, isouter=True)
        .where(
            WbOrder.tenant_id == tenant_id,
            WbOrder.order_dt >= dt_from,
            WbOrder.order_dt <= dt_to,
            # «is_cancel» исключаем — нет смысла оценивать локализацию
            # отменённого заказа (он не был отгружен).
            WbOrder.is_cancel.is_(False),
        )
    )

    if brand_list is not None:
        # brand_list = пустой → manager без assignments → пустой результат.
        if not brand_list:
            return LocalizationStats(
                period_from=period_from,
                period_to=period_to,
                total_orders=0,
                localized_orders=0,
                localization_pct=0.0,
                by_cluster=[],
                by_brand=[],
                by_warehouse=[],
                worst_skus=[],
                heatmap=[],
            )
        stmt = stmt.where(Product.brand.in_(brand_list))

    rows = (await session.execute(stmt)).all()

    # --- Агрегация в памяти (одна выборка → много breakdown'ов) ---
    total = 0
    localized = 0

    cluster_buckets: dict[str, dict[str, float]] = {}
    brand_buckets: dict[str, dict[str, float]] = {}
    warehouse_buckets: dict[str, dict[str, float]] = {}
    sku_buckets: dict[int, dict[str, float | str | None]] = {}
    heatmap_buckets: dict[tuple[str, str, str], int] = {}

    for r in rows:
        wh_cluster = cluster_for_warehouse(r.warehouse_name)
        buyer_cluster = cluster_for_oblast(r.oblast, r.region_name)
        localized_flag = (
            wh_cluster != "OTHER"
            and buyer_cluster != "OTHER"
            and wh_cluster == buyer_cluster
        )

        total += 1
        if localized_flag:
            localized += 1

        # by_cluster — bucket'имся по кластеру ПОКУПАТЕЛЯ (для UI важнее).
        cb = cluster_buckets.setdefault(
            buyer_cluster,
            {"orders": 0, "localized": 0, "revenue": 0.0},
        )
        cb["orders"] = int(cb["orders"]) + 1
        if localized_flag:
            cb["localized"] = int(cb["localized"]) + 1
        cb["revenue"] = float(cb["revenue"]) + float(r.total_price or 0)

        # by_brand
        brand_key = (r.p_brand or r.brand or "").strip()
        bb = brand_buckets.setdefault(
            brand_key, {"orders": 0, "localized": 0}
        )
        bb["orders"] = int(bb["orders"]) + 1
        if localized_flag:
            bb["localized"] = int(bb["localized"]) + 1

        # by_warehouse
        wh_key = r.warehouse_name or "(unknown)"
        wb = warehouse_buckets.setdefault(
            wh_key,
            {"orders": 0, "localized": 0, "cluster": wh_cluster},
        )
        wb["orders"] = int(wb["orders"]) + 1
        if localized_flag:
            wb["localized"] = int(wb["localized"]) + 1

        # by_sku
        sb = sku_buckets.setdefault(
            int(r.nm_id),
            {
                "orders": 0,
                "localized": 0,
                "vendor_code": r.vendor_code,
                "brand": r.p_brand or r.brand,
                "subject": r.p_subject,
            },
        )
        sb["orders"] = int(sb["orders"]) + 1  # type: ignore[arg-type]
        if localized_flag:
            sb["localized"] = int(sb["localized"]) + 1  # type: ignore[arg-type]

        # heatmap warehouse × buyer_cluster
        hkey = (wh_key, wh_cluster, buyer_cluster)
        heatmap_buckets[hkey] = heatmap_buckets.get(hkey, 0) + 1

    # --- Преобразование в DTO ---

    by_cluster = [
        ClusterLocalization(
            cluster=code,
            cluster_label=cluster_label(code),
            orders=int(b["orders"]),
            localized_orders=int(b["localized"]),
            localization_pct=_safe_pct(int(b["localized"]), int(b["orders"])),
            revenue=float(b["revenue"]),
        )
        for code, b in cluster_buckets.items()
    ]
    # Сортировка: фиксированный order для центральных, OTHER в конец.
    def _cluster_sort_key(c: ClusterLocalization) -> tuple[int, str]:
        try:
            return (CLUSTER_ORDER.index(c.cluster), c.cluster)
        except ValueError:
            return (99, c.cluster)

    by_cluster.sort(key=_cluster_sort_key)

    # TASK-LEAD-085: фильтр по минимальному объёму + WoW п.п. за prev week.
    # Previous-period окно — тот же размер сдвинутый назад (immediately
    # adjacent, не overlap). Для периода 2026-05-15..2026-05-21 prev =
    # 2026-05-08..2026-05-14.
    period_days = (period_to - period_from).days + 1
    prev_to = period_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)
    prev_brand_pct = await _compute_brand_pct_map(
        session=session,
        tenant_id=tenant_id,
        period_from=prev_from,
        period_to=prev_to,
        brands=brand_list,
        min_orders=brand_min_orders,
    )

    by_brand: list[BrandLocalization] = []
    for name, b in brand_buckets.items():
        orders_n = int(b["orders"])
        # min_orders threshold — отсекаем статистический шум.
        if orders_n < brand_min_orders:
            continue
        loc_n = int(b["localized"])
        curr_pct = _safe_pct(loc_n, orders_n)
        prev_pct = prev_brand_pct.get(name)
        wow_pct = (
            round(curr_pct - prev_pct, 2) if prev_pct is not None else None
        )
        by_brand.append(
            BrandLocalization(
                brand=name,
                orders=orders_n,
                localized_orders=loc_n,
                localization_pct=curr_pct,
                wow_pct=wow_pct,
            )
        )
    by_brand.sort(key=lambda x: x.orders, reverse=True)

    by_warehouse = [
        WarehouseLocalization(
            warehouse=name,
            cluster=str(b["cluster"]),
            cluster_label=cluster_label(str(b["cluster"])),
            orders=int(b["orders"]),
            localized_orders=int(b["localized"]),
            localization_pct=_safe_pct(int(b["localized"]), int(b["orders"])),
        )
        for name, b in warehouse_buckets.items()
    ]
    by_warehouse.sort(key=lambda x: x.orders, reverse=True)

    # worst_skus — низкая локализация при достаточном объёме (>= 5 заказов).
    sku_items: list[SkuLocalization] = []
    for nm_id, b in sku_buckets.items():
        orders_n = int(b["orders"])  # type: ignore[arg-type]
        if orders_n < 5:
            continue
        loc_n = int(b["localized"])  # type: ignore[arg-type]
        sku_items.append(
            SkuLocalization(
                nm_id=nm_id,
                vendor_code=(
                    str(b["vendor_code"]) if b["vendor_code"] is not None else None
                ),
                brand=str(b["brand"]) if b["brand"] is not None else None,
                subject=str(b["subject"]) if b["subject"] is not None else None,
                orders=orders_n,
                localized_orders=loc_n,
                localization_pct=_safe_pct(loc_n, orders_n),
            )
        )
    # худшие = низкий localization_pct + tie-break по объёму (больше заказов
    # = больший импакт).
    sku_items.sort(key=lambda x: (x.localization_pct, -x.orders))
    worst_skus = sku_items[:worst_sku_limit]

    # heatmap
    heatmap = [
        LocalizationHeatmapCell(
            warehouse=wh,
            warehouse_cluster=whc,
            buyer_cluster=bc,
            orders=cnt,
        )
        for (wh, whc, bc), cnt in heatmap_buckets.items()
    ]
    # Срезаем хвост: оставляем top-50 ячеек по объёму, чтобы UI heatmap'а
    # не пытался отрендерить 1000+ комбинаций для крупных тенантов.
    heatmap.sort(key=lambda c: c.orders, reverse=True)
    heatmap = heatmap[:200]

    return LocalizationStats(
        period_from=period_from,
        period_to=period_to,
        total_orders=total,
        localized_orders=localized,
        localization_pct=_safe_pct(localized, total),
        by_cluster=by_cluster,
        by_brand=by_brand,
        by_warehouse=by_warehouse,
        worst_skus=worst_skus,
        heatmap=heatmap,
    )
