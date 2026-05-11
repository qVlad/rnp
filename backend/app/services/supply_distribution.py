"""Распределение поставки по кластерам с учётом ИЛ и ИРП.

Метрики per nm_id:
  - **ИРП** (индекс распределения продаж) — доля продаж по кластеру покупателя
    за окно (по умолчанию 30 дней). Σ ИРП по кластерам = 100%.
  - **ИЛ** (индекс локализации) — доля продаж, в которых склад отгрузки
    находится в том же кластере, что и покупатель. От 0 до 100%, выше = лучше.
  - **stock_by_cluster** — текущий остаток по кластерам (из последнего snapshot).
  - **target_by_cluster** — целевой остаток по кластеру = recommended_total × ИРП.
  - **deficit_by_cluster** — сколько везти в каждый кластер = max(0, target − stock).

ИРП считаем по `wb_sales.oblast` покупателя (с fallback на `region_name`
для зарубежья). ИЛ — по совпадению `cluster(warehouse_name) == cluster(oblast)`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbSale, WbStockSnapshot
from app.services.clusters import (
    CLUSTER_LABELS,
    CLUSTER_ORDER,
    cluster_for_oblast,
    cluster_for_warehouse,
)


def _empty_cluster_dict(default: float = 0.0) -> dict[str, float]:
    return {c: default for c in CLUSTER_ORDER}


def _size_sort_key(s: str) -> tuple[int, float, str]:
    """Сортировка размеров: числовые по возрастанию, потом буквенные алфавитно.

    "—" (без размера) — в самом конце.
    """
    if s == "—":
        return (2, 0.0, "")
    try:
        return (0, float(s.replace(",", ".").split("-")[0].split("/")[0]), s)
    except (ValueError, IndexError):
        return (1, 0.0, s.lower())


async def build_supply_distribution(
    session: AsyncSession,
    *,
    velocity_window: int = 14,
    target_days: int = 30,
    irp_window: int = 30,
    include_archived: bool = False,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Per-nm cluster distribution. Возвращает items, аналогичные stockout-forecast,
    но с дополнительными полями `clusters`, `irp`, `il_pct`.

    `velocity_window` — окно для расчёта velocity (как в stockout).
    `irp_window` — окно для расчёта ИРП и ИЛ (по умолчанию шире, для стабильности).
    """
    end = datetime.now(timezone.utc)
    vel_start = end - timedelta(days=velocity_window)
    irp_start = end - timedelta(days=irp_window)

    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    # 1) Velocity per nm (для recommended_total, как в stockout-forecast).
    vel_stmt = (
        select(
            WbSale.nm_id,
            func.coalesce(func.sum(case((WbSale.is_return, -1), else_=1)), 0).label("net_qty"),
        )
        .where(WbSale.sale_dt >= vel_start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        vel_stmt = vel_stmt.where(WbSale.nm_id.in_(nm_filter))
    vel_rows = (await session.execute(vel_stmt)).all()
    velocity_by_nm: dict[int, float] = {
        int(r.nm_id): float(r.net_qty or 0) / max(velocity_window, 1) for r in vel_rows
    }

    # 2) Sales за окно ИРП с привязкой к oblast/warehouse_name И размеру.
    sales_stmt = (
        select(
            WbSale.nm_id,
            WbSale.warehouse_name,
            WbSale.oblast,
            WbSale.region_name,
            WbSale.tech_size,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
        )
        .where(WbSale.sale_dt >= irp_start, WbSale.sale_dt < end)
        .group_by(
            WbSale.nm_id,
            WbSale.warehouse_name,
            WbSale.oblast,
            WbSale.region_name,
            WbSale.tech_size,
        )
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_rows = (await session.execute(sales_stmt)).all()

    # Накапливаем:
    #   irp_by_nm[nm][cluster] = units (для ИРП)
    #   irp_size_by_nm[nm][cluster][size] = units (для распределения по размерам в кластере)
    #   size_total_by_nm[nm][size] = units (для глобальной доли размера, fallback)
    #   il_* — счётчики локальности.
    irp_by_nm: dict[int, dict[str, float]] = {}
    irp_size_by_nm: dict[int, dict[str, dict[str, float]]] = {}
    size_total_by_nm: dict[int, dict[str, float]] = {}
    il_local_by_nm: dict[int, float] = {}
    il_total_by_nm: dict[int, float] = {}
    for r in sales_rows:
        nm = int(r.nm_id)
        units = float(r.units or 0)
        if units <= 0:
            continue  # чистый возврат — не учитываем
        buyer_c = cluster_for_oblast(r.oblast, r.region_name)
        wh_c = cluster_for_warehouse(r.warehouse_name)
        size = r.tech_size or "—"

        d = irp_by_nm.setdefault(nm, _empty_cluster_dict())
        d[buyer_c] = d.get(buyer_c, 0.0) + units

        cluster_sizes = irp_size_by_nm.setdefault(nm, {}).setdefault(buyer_c, {})
        cluster_sizes[size] = cluster_sizes.get(size, 0.0) + units

        sizes = size_total_by_nm.setdefault(nm, {})
        sizes[size] = sizes.get(size, 0.0) + units

        il_total_by_nm[nm] = il_total_by_nm.get(nm, 0.0) + units
        if wh_c == buyer_c and buyer_c not in ("OTHER",):
            il_local_by_nm[nm] = il_local_by_nm.get(nm, 0.0) + units

    # 3) Stock per (nm, cluster, size) из последнего snapshot.
    latest_dt = select(func.max(WbStockSnapshot.snapshot_dt)).scalar_subquery()
    stock_stmt = (
        select(
            WbStockSnapshot.nm_id,
            WbStockSnapshot.warehouse_name,
            WbStockSnapshot.tech_size,
            func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
        )
        .where(WbStockSnapshot.snapshot_dt == latest_dt)
        .group_by(
            WbStockSnapshot.nm_id,
            WbStockSnapshot.warehouse_name,
            WbStockSnapshot.tech_size,
        )
    )
    if nm_filter is not None:
        stock_stmt = stock_stmt.where(WbStockSnapshot.nm_id.in_(nm_filter))
    stock_rows = (await session.execute(stock_stmt)).all()
    stock_by_nm_cluster: dict[int, dict[str, int]] = {}
    stock_by_nm_cluster_size: dict[int, dict[str, dict[str, int]]] = {}
    stock_total_by_nm: dict[int, int] = {}
    for r in stock_rows:
        nm = int(r.nm_id)
        c = cluster_for_warehouse(r.warehouse_name)
        size = r.tech_size or "—"
        qty = int(r.qty or 0)
        d = stock_by_nm_cluster.setdefault(nm, _empty_cluster_dict(0))
        d[c] = int(d.get(c, 0)) + qty
        stock_by_nm_cluster_size.setdefault(nm, {}).setdefault(c, {})
        stock_by_nm_cluster_size[nm][c][size] = (
            stock_by_nm_cluster_size[nm][c].get(size, 0) + qty
        )
        stock_total_by_nm[nm] = stock_total_by_nm.get(nm, 0) + qty

    # 4) Products + archive filter.
    products_stmt = select(Product)
    if brands is not None:
        products_stmt = products_stmt.where(Product.brand.in_(list(brands)))
    all_products = (await session.execute(products_stmt)).scalars().all()
    products = {p.nm_id: p for p in all_products}
    archived = (
        set() if include_archived else {p.nm_id for p in all_products if p.is_archived}
    )

    nm_set = set(velocity_by_nm.keys()) | set(stock_total_by_nm.keys()) | set(irp_by_nm.keys())
    nm_set -= archived

    items: list[dict[str, Any]] = []
    aggregate_il_local = 0.0
    aggregate_il_total = 0.0
    for nm in nm_set:
        prod = products.get(nm)
        velocity = velocity_by_nm.get(nm, 0.0)
        stock_total = stock_total_by_nm.get(nm, 0)
        recommended_total = (
            max(0, int(round(velocity * target_days - stock_total))) if velocity > 0 else 0
        )

        # ИРП (нормированные доли, сумма = 100%).
        raw_irp = irp_by_nm.get(nm, _empty_cluster_dict())
        total_units = sum(raw_irp.values())
        irp_pct = (
            {c: round(v / total_units * 100, 1) for c, v in raw_irp.items()}
            if total_units > 0
            else _empty_cluster_dict()
        )

        # ИЛ (локальные продажи / все продажи) × 100.
        local = il_local_by_nm.get(nm, 0.0)
        tot = il_total_by_nm.get(nm, 0.0)
        il_pct = round(local / tot * 100, 1) if tot > 0 else 0.0
        aggregate_il_local += local
        aggregate_il_total += tot

        # Глобальные доли размеров (fallback для кластеров без статистики
        # размеров — часто свежие SKU имеют продажи только в одном кластере,
        # но на склады нужно везти все размеры пропорционально общим продажам).
        nm_sizes_total = size_total_by_nm.get(nm, {})
        nm_sizes_total_sum = sum(nm_sizes_total.values())
        global_size_share: dict[str, float] = (
            {s: v / nm_sizes_total_sum for s, v in nm_sizes_total.items()}
            if nm_sizes_total_sum > 0
            else {}
        )

        # Cluster breakdown: stock + target + deficit + sizes.
        stock_c = stock_by_nm_cluster.get(nm, _empty_cluster_dict(0))
        stock_cs = stock_by_nm_cluster_size.get(nm, {})
        irp_size_c = irp_size_by_nm.get(nm, {})
        clusters: list[dict[str, Any]] = []
        for code in CLUSTER_ORDER:
            irp_v = irp_pct.get(code, 0.0)
            cluster_target = (
                int(round(recommended_total * irp_v / 100)) if recommended_total > 0 else 0
            )
            stock_v = int(stock_c.get(code, 0))

            # Per-size breakdown в этом кластере. Берём доли размеров из продаж
            # этого же кластера; если их < 5 единиц — fallback на глобальные
            # доли по SKU (свежие позиции с однородной географией).
            cluster_size_sales = irp_size_c.get(code, {})
            cluster_size_sum = sum(cluster_size_sales.values())
            if cluster_size_sum >= 5:
                size_share = {
                    s: v / cluster_size_sum for s, v in cluster_size_sales.items()
                }
            else:
                size_share = global_size_share

            cluster_size_stock = stock_cs.get(code, {})

            # Полный набор размеров: те, что есть в продажах ИЛИ на стоке кластера.
            all_sizes: set[str] = set(size_share.keys()) | set(cluster_size_stock.keys())
            sizes_breakdown: list[dict[str, Any]] = []
            for s in sorted(all_sizes, key=_size_sort_key):
                share = size_share.get(s, 0.0)
                size_target = int(round(cluster_target * share)) if cluster_target > 0 else 0
                size_stock = int(cluster_size_stock.get(s, 0))
                size_deficit = max(0, size_target - size_stock)
                sizes_breakdown.append(
                    {
                        "size": s,
                        "share_pct": round(share * 100, 1),
                        "stock": size_stock,
                        "target_qty": size_target,
                        "deficit": size_deficit,
                    }
                )

            # Deficit на уровне кластера = СУММА дефицитов по размерам
            # (нельзя «погасить» нехватку 42-го размера остатком 36-го).
            # При этом цель `cluster_target` остаётся cluster-level.
            cluster_deficit = sum(s["deficit"] for s in sizes_breakdown)

            clusters.append(
                {
                    "code": code,
                    "label": CLUSTER_LABELS[code],
                    "irp_pct": irp_v,
                    "stock": stock_v,
                    "target_qty": cluster_target,
                    "deficit": cluster_deficit,
                    "sizes": sizes_breakdown,
                }
            )

        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": prod.brand if prod else None,
                "velocity_per_day": round(velocity, 3),
                "stock_total": stock_total,
                "recommended_total": recommended_total,
                "il_pct": il_pct,
                "clusters": clusters,
            }
        )

    # Сортируем по дефициту (сумма по кластерам desc), потом по velocity.
    items.sort(
        key=lambda it: (-sum(c["deficit"] for c in it["clusters"]), -it["velocity_per_day"])
    )

    aggregate_il = (
        round(aggregate_il_local / aggregate_il_total * 100, 1)
        if aggregate_il_total > 0
        else 0.0
    )
    return {
        "velocity_window": velocity_window,
        "irp_window": irp_window,
        "target_days": target_days,
        "aggregate_il_pct": aggregate_il,
        "cluster_order": CLUSTER_ORDER,
        "cluster_labels": CLUSTER_LABELS,
        "items": items,
    }
