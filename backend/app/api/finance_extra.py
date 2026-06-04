"""Доп. финансовые/складские отчёты под разделы TrueStats (TASK-DEV-041/042/044).

- GET /api/deductions       — «Прочие удержания»: разбивка report_detail по типам
  операций (Логистика / Хранение / Штраф / Удержание / Возмещение …) за период.
- GET /api/operations       — «Операции»: построчный реестр report_detail (как
  выписка) с пагинацией и фильтром по типу.
- GET /api/stocks/by-warehouse — «Склады»: остатки по складам WB (последний
  снапшот) в разрезе склад × SKU.

Все — director/head (финансы). reporting_mode (sale_dt|rr_dt) для deductions/
operations через period_aggregates.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbReportDetail, WbStockSnapshot
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(tags=["finance-extra"])

# Типы операций report_detail, которые НЕ продажа/возврат — «прочие удержания».
_SALE_RETURN = ("Продажа", "Возврат")


def _date_col(reporting_mode: str):
    return WbReportDetail.rr_dt if reporting_mode == "financial" else WbReportDetail.sale_dt


@router.get("/api/deductions", dependencies=[Depends(require_director_or_head)])
async def get_deductions(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Разбивка удержаний WB по типам операций за период."""
    dcol = _date_col(reporting_mode)
    rows = (
        await session.execute(
            select(
                WbReportDetail.supplier_oper_name.label("op"),
                func.count().label("n"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("delivery"),
                func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(WbReportDetail.deduction), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.acquiring_fee), 0).label("acquiring"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date)
            .group_by(WbReportDetail.supplier_oper_name)
        )
    ).all()

    def _f(v: Any) -> float:
        return float(v or 0)

    items = []
    for r in rows:
        amount = _f(r.delivery) + _f(r.storage) + _f(r.penalty) + _f(r.deduction) + _f(r.acquiring)
        # Для продажи/возврата суммы удержаний считаем по их компонентам, но в
        # «прочие удержания» показываем не-торговые операции отдельно.
        items.append(
            {
                "operation": r.op,
                "count": int(r.n),
                "delivery": _f(r.delivery),
                "storage": _f(r.storage),
                "penalty": _f(r.penalty),
                "deduction": _f(r.deduction),
                "acquiring": _f(r.acquiring),
                "total": round(amount, 2),
            }
        )
    items.sort(key=lambda x: abs(x["total"]), reverse=True)
    total = round(sum(x["total"] for x in items), 2)
    return {"reporting_mode": reporting_mode, "items": items, "total": total}


@router.get("/api/operations", dependencies=[Depends(require_director_or_head)])
async def get_operations(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    operation: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Построчный реестр операций report_detail за период (как выписка)."""
    dcol = _date_col(reporting_mode)
    base = select(WbReportDetail).where(
        func.date(dcol) >= start_date, func.date(dcol) <= end_date
    )
    if operation:
        base = base.where(WbReportDetail.supplier_oper_name == operation)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(dcol.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    def _f(v: Any) -> float:
        return float(v or 0)

    items = [
        {
            "rrd_id": r.rrd_id,
            "sale_dt": r.sale_dt.isoformat() if r.sale_dt else None,
            "rr_dt": r.rr_dt.isoformat() if r.rr_dt else None,
            "nm_id": r.nm_id,
            "sa_name": r.sa_name,
            "operation": r.supplier_oper_name,
            "quantity": r.quantity,
            "retail_price": _f(r.retail_price),
            "retail_amount": _f(r.retail_amount),
            "ppvz_for_pay": _f(r.ppvz_for_pay),
            "delivery_rub": _f(r.delivery_rub),
            "storage_fee": _f(r.storage_fee),
            "penalty": _f(r.penalty),
            "deduction": _f(r.deduction),
        }
        for r in rows
    ]
    return {"total": int(total), "limit": limit, "offset": offset, "items": items}


@router.get("/api/stocks/by-warehouse", dependencies=[Depends(require_director_or_head)])
async def stocks_by_warehouse(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Остатки по складам WB — последний снапшот, склад × SKU."""
    # Последний snapshot_dt в таблице.
    last_dt = (
        await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
    ).scalar_one_or_none()
    if last_dt is None:
        return {"snapshot_dt": None, "warehouses": [], "items": []}

    rows = (
        await session.execute(
            select(
                WbStockSnapshot.warehouse_name.label("wh"),
                WbStockSnapshot.nm_id,
                func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
                func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("to_client"),
                func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("from_client"),
            )
            .where(WbStockSnapshot.snapshot_dt == last_dt)
            .group_by(WbStockSnapshot.warehouse_name, WbStockSnapshot.nm_id)
        )
    ).all()

    # Имена товаров.
    nm_ids = list({int(r.nm_id) for r in rows if r.nm_id})
    names: dict[int, dict[str, Any]] = {}
    if nm_ids:
        prods = (
            await session.execute(
                select(Product.nm_id, Product.vendor_code, Product.brand).where(
                    Product.nm_id.in_(nm_ids)
                )
            )
        ).all()
        names = {int(p.nm_id): {"vendor_code": p.vendor_code, "brand": p.brand} for p in prods}

    items = [
        {
            "warehouse": r.wh,
            "nm_id": int(r.nm_id),
            "vendor_code": names.get(int(r.nm_id), {}).get("vendor_code"),
            "brand": names.get(int(r.nm_id), {}).get("brand"),
            "qty": int(r.qty),
            "in_way_to_client": int(r.to_client),
            "in_way_from_client": int(r.from_client),
        }
        for r in rows
    ]
    items.sort(key=lambda x: x["qty"], reverse=True)
    # Сводка по складам.
    wh_totals: dict[str, int] = {}
    for it in items:
        wh_totals[it["warehouse"] or "—"] = wh_totals.get(it["warehouse"] or "—", 0) + it["qty"]
    warehouses = sorted(
        ({"warehouse": k, "qty": v} for k, v in wh_totals.items()),
        key=lambda x: x["qty"],
        reverse=True,
    )
    return {"snapshot_dt": last_dt.isoformat(), "warehouses": warehouses, "items": items}
