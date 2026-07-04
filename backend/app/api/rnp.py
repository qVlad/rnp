"""API модуля РНП (TASK-DEV-094): матрица метрики×дни + настройки артикулов.

GET /api/rnp/matrix?from&to(&brands&categories&groups&articles&stores)
GET /api/rnp/sku-selection            → список SKU с флагом enabled
PUT /api/rnp/sku-selection            → bulk {items: [{nm_id, enabled}]}
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, Product, RnpSkuSelection
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.rnp_matrix import build_rnp_matrix, get_rnp_nm_scope
from app.services.tenant_context import get_tenant, set_tenant_filter

router = APIRouter(prefix="/api/rnp", tags=["rnp"])


@router.get("/matrix", dependencies=[Depends(require_director_or_head)])
async def rnp_matrix(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    brands: Annotated[str | None, Query()] = None,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id,
        rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(
        session, brands=brands, categories=categories, groups=groups, articles=articles
    )
    nm_scope = await get_rnp_nm_scope(session, nm_scope)
    return await build_rnp_matrix(
        session, date_from=date_from, date_to=date_to, nm_scope=nm_scope
    )


@router.get("/sku-selection", dependencies=[Depends(require_director_or_head)])
async def list_sku_selection(
    q: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Все SKU tenant'а + флаг показа в РНП (нет строк выбора = все включены)."""
    stmt = select(Product.nm_id, Product.vendor_code, Product.brand,
                  Product.category, Product.subject, Product.photo_url)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Product.vendor_code.ilike(like)
            | Product.brand.ilike(like)
            | Product.subject.ilike(like)
        )
    prows = (await session.execute(stmt.order_by(Product.brand, Product.vendor_code))).all()
    sel = {
        int(nm): en
        for nm, en in (
            await session.execute(select(RnpSkuSelection.nm_id, RnpSkuSelection.enabled))
        ).all()
    }
    has_selection = bool(sel)
    return {
        "has_selection": has_selection,
        "items": [
            {
                "nm_id": int(p.nm_id),
                "vendor_code": p.vendor_code,
                "brand": p.brand,
                "category": p.category,
                "subject": p.subject,
                "photo_url": p.photo_url,
                # без явного выбора всё включено; с выбором — только отмеченные
                "enabled": sel.get(int(p.nm_id), not has_selection),
            }
            for p in prows
        ],
    }


@router.put("/sku-selection", dependencies=[Depends(require_director_or_head)])
async def set_sku_selection(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Bulk-upsert выбора: {items: [{nm_id, enabled}]}."""
    items = payload.get("items") or []
    existing = {
        int(r.nm_id): r
        for r in (await session.execute(select(RnpSkuSelection))).scalars()
    }
    tid = get_tenant(session)
    updated = 0
    for it in items:
        try:
            nm = int(it.get("nm_id"))
        except (TypeError, ValueError):
            continue
        enabled = bool(it.get("enabled"))
        row = existing.get(nm)
        if row is None:
            session.add(RnpSkuSelection(tenant_id=tid, nm_id=nm, enabled=enabled))
        else:
            row.enabled = enabled
        updated += 1
    await session.commit()
    return {"updated": updated}


_FORECAST_KEY = "rnp_forecast_window"  # "7" | "28" | "period"


@router.get("/forecast-window", dependencies=[Depends(require_director_or_head)])
async def get_forecast_window(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Окно усреднения прогнозных коэффициентов РНП (DEV-096, как TS 7/28 дней).

    "7"/"28" — последние полные календарные недели с финотчётом;
    "period" — коэффициенты по выбранному в матрице периоду (наше поведение
    по умолчанию до DEV-096).
    """
    tid = get_tenant(session)
    # pitfall #16: AppSetting без tenant-mixin — фильтруем явно.
    row = (
        await session.execute(
            select(AppSetting.value).where(
                AppSetting.tenant_id == tid, AppSetting.key == _FORECAST_KEY
            )
        )
    ).scalar_one_or_none()
    return {"window": row if row in ("7", "28", "period") else "period"}


@router.put("/forecast-window", dependencies=[Depends(require_director_or_head)])
async def set_forecast_window(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    window = str(payload.get("window") or "")
    if window not in ("7", "28", "period"):
        from fastapi import HTTPException

        raise HTTPException(422, "window ∈ 7|28|period")
    tid = get_tenant(session)
    row = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tid, AppSetting.key == _FORECAST_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(AppSetting(tenant_id=tid, key=_FORECAST_KEY, value=window))
    else:
        row.value = window
    await session.commit()
    return {"window": window}
