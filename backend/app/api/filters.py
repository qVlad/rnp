"""Глобальные фильтры (TASK-DEV-062) — опции для панели фильтров.

GET /api/filters/options — доступные значения измерений (бренды/категории/группы/
артикулы) для активного кабинета, с учётом RBAC (manager-scope). Магазины
(мульти-кабинет) — отдельная фаза.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductGroup, ProductGroupAssignment
from app.services.auth import current_brands_filter, get_db_tenant_scoped

router = APIRouter(tags=["filters"])


@router.get("/api/filters/options")
async def filter_options(
    brands: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    rbac_brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Опции фильтров для активного кабинета.

    Каскад: если выбраны `brands` — категории/артикулы сужаются до этих брендов
    (как в TS). RBAC: manager видит только свои бренды.
    """
    # Базовый предикат продукта под RBAC.
    base = select(Product)
    if rbac_brands is not None:
        base = base.where(Product.brand.in_(rbac_brands))

    # Бренды (всегда полный список доступных под RBAC).
    brow = (await session.execute(
        select(Product.brand, func.count()).where(
            Product.brand.isnot(None), *( [Product.brand.in_(rbac_brands)] if rbac_brands is not None else [] )
        ).group_by(Product.brand).order_by(func.count().desc())
    )).all()
    brand_opts = [{"value": b, "count": int(c)} for b, c in brow if b]

    # Каскадный фильтр для категорий/артикулов.
    sel_brands = [x.strip() for x in (brands or "").split(",") if x.strip()]
    cat_q = select(Product.category, func.count()).where(Product.category.isnot(None))
    art_q = select(Product.nm_id, Product.vendor_code, Product.brand).where(Product.nm_id.isnot(None))
    if rbac_brands is not None:
        cat_q = cat_q.where(Product.brand.in_(rbac_brands))
        art_q = art_q.where(Product.brand.in_(rbac_brands))
    if sel_brands:
        cat_q = cat_q.where(Product.brand.in_(sel_brands))
        art_q = art_q.where(Product.brand.in_(sel_brands))
    cat_q = cat_q.group_by(Product.category).order_by(func.count().desc())

    crow = (await session.execute(cat_q)).all()
    cat_opts = [{"value": c, "count": int(n)} for c, n in crow if c]

    arow = (await session.execute(art_q.order_by(Product.vendor_code))).all()
    art_opts = [{"value": int(nm), "label": vc or str(nm), "brand": br} for nm, vc, br in arow if nm]

    # Группы товаров.
    grow = (await session.execute(
        select(ProductGroup.id, ProductGroup.name, func.count(ProductGroupAssignment.nm_id))
        .outerjoin(ProductGroupAssignment, ProductGroupAssignment.group_id == ProductGroup.id)
        .group_by(ProductGroup.id, ProductGroup.name)
        .order_by(ProductGroup.name)
    )).all()
    group_opts = [{"value": int(gid), "label": name, "count": int(n)} for gid, name, n in grow]

    return {
        "brands": brand_opts,
        "categories": cat_opts,
        "groups": group_opts,
        "articles": art_opts,
    }
