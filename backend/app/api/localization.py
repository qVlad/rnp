"""Локализация заказов API (TASK-LEAD-052).

`GET /api/localization?from=YYYY-MM-DD&to=YYYY-MM-DD&brand=<опц>` —
посчитать % локализации заказов за период + breakdown по
(кластеру покупателя | бренду | складу | худшим SKU).

Локализация := склад_кластер == покупатель_кластер (см.
`services/localization.py` и `services/clusters.py`).

RBAC: brands-filter (manager видит только свои бренды).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    current_brands_filter,
    current_tenant_id,
    get_db_tenant_scoped,
)
from app.services.localization import compute_localization

router = APIRouter(prefix="/api/localization", tags=["localization"])


def _parse_period(
    from_: str | None,
    to: str | None,
    default_days: int = 30,
) -> tuple[date, date]:
    """Парсим YYYY-MM-DD; дефолт — последние `default_days` дней."""
    today = date.today()
    if to is None:
        period_to = today
    else:
        period_to = date.fromisoformat(to)
    if from_ is None:
        period_from = period_to - timedelta(days=default_days - 1)
    else:
        period_from = date.fromisoformat(from_)
    if period_from > period_to:
        period_from, period_to = period_to, period_from
    return period_from, period_to


@router.get("")
async def localization_summary(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    brand: str | None = Query(default=None, description="опц. фильтр по бренду"),
    worst_sku_limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    tenant_id: int = Depends(current_tenant_id),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Сводка по локализации за период.

    Query params:
      - `from`, `to` — YYYY-MM-DD (включительно с обеих сторон).
        Если оба не указаны — последние 30 дней.
      - `brand` — опц. сузить выборку до одного бренда (поверх RBAC-фильтра).
      - `worst_sku_limit` — сколько SKU в worst-list (default 10).

    Возвращает: LocalizationStats как dict (см. `services/localization.py`).
    """
    period_from, period_to = _parse_period(from_, to)

    # Сужение по `brand` поверх RBAC. RBAC выдаёт `brands` (set | None):
    #   None ⇒ unrestricted (director / head)
    #   set  ⇒ manager — пересечение с явным `brand` (если задан)
    if brand is not None:
        if brands is None:
            effective_brands: set[str] | None = {brand}
        else:
            effective_brands = brands & {brand}
    else:
        effective_brands = brands

    stats = await compute_localization(
        session=session,
        tenant_id=tenant_id,
        period_from=period_from,
        period_to=period_to,
        brands=effective_brands,
        worst_sku_limit=worst_sku_limit,
    )

    return {
        "period_from": stats.period_from.isoformat(),
        "period_to": stats.period_to.isoformat(),
        "total_orders": stats.total_orders,
        "localized_orders": stats.localized_orders,
        "localization_pct": stats.localization_pct,
        "by_cluster": [asdict(c) for c in stats.by_cluster],
        "by_brand": [asdict(b) for b in stats.by_brand],
        "by_warehouse": [asdict(w) for w in stats.by_warehouse],
        "worst_skus": [asdict(s) for s in stats.worst_skus],
        "heatmap": [asdict(h) for h in stats.heatmap],
    }
