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

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import get_current_user

from app.db.models import (
    FinanceReference,
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbReportDetail,
    WbStockSnapshot,
)
from app.services.tenant_context import get_tenant
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(tags=["finance-extra"])

# Типы операций report_detail, которые НЕ продажа/возврат — «прочие удержания».
_SALE_RETURN = ("Продажа", "Возврат")


def _date_col(reporting_mode: str):
    return WbReportDetail.rr_dt if reporting_mode == "financial" else WbReportDetail.sale_dt


_REF_TYPES = {"expense_category", "counterparty", "account"}


@router.get("/api/finance-reference", dependencies=[Depends(require_director_or_head)])
async def list_finance_reference(
    ref_type: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Справочники операций (TASK-DEV-043): статьи расходов / контрагенты / счета."""
    stmt = select(FinanceReference).order_by(FinanceReference.ref_type, FinanceReference.name)
    if ref_type:
        stmt = stmt.where(FinanceReference.ref_type == ref_type)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {"id": r.id, "ref_type": r.ref_type, "name": r.name, "extra": r.extra or {}}
            for r in rows
        ]
    }


@router.post("/api/finance-reference", dependencies=[Depends(require_director_or_head)])
async def create_finance_reference(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    ref_type = str(payload.get("ref_type") or "")
    name = str(payload.get("name") or "").strip()
    if ref_type not in _REF_TYPES:
        raise HTTPException(400, f"ref_type должен быть из {_REF_TYPES}")
    if not name:
        raise HTTPException(400, "name обязателен")
    obj = FinanceReference(
        tenant_id=get_tenant(session),
        ref_type=ref_type,
        name=name,
        extra=payload.get("extra") or None,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return {"id": obj.id, "ref_type": obj.ref_type, "name": obj.name, "extra": obj.extra or {}}


@router.delete("/api/finance-reference/{ref_id}", dependencies=[Depends(require_director_or_head)])
async def delete_finance_reference(
    ref_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(FinanceReference).where(FinanceReference.id == ref_id))
    await session.commit()
    return {"status": "deleted", "id": ref_id}


@router.get("/api/business-summary", dependencies=[Depends(require_director_or_head)])
async def business_summary(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Сводный по бизнесу (TASK-DEV-040): свод по всем доступным пользователю
    кабинетам. Raw SQL обходит per-tenant ORM-фильтр, но ограничен tenant'ами
    из user_tenant_access (безопасно)."""
    dcol = "rr_dt" if reporting_mode == "financial" else "sale_dt"
    acc = (
        await session.execute(
            text("select tenant_id from user_tenant_access where user_id = :u"),
            {"u": user.id},
        )
    ).all()
    tids = [r[0] for r in acc] or [user.tenant_id]
    names = {
        r[0]: r[1]
        for r in (
            await session.execute(
                text("select id, name from tenants where id = any(:ids)"),
                {"ids": tids},
            )
        ).all()
    }
    agg = (
        await session.execute(
            text(
                f"""
            select tenant_id,
              coalesce(sum(case when supplier_oper_name='Продажа' then retail_price else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then retail_price else 0 end),0) realisation,
              coalesce(sum(case when supplier_oper_name='Продажа' then retail_amount else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then retail_amount else 0 end),0) sales,
              coalesce(sum(case when supplier_oper_name='Продажа' then ppvz_for_pay else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then ppvz_for_pay else 0 end),0) to_transfer,
              coalesce(sum(case when supplier_oper_name='Продажа' then quantity else 0 end),0) sold
            from wb_report_detail
            where tenant_id = any(:ids) and {dcol}::date between :lo and :hi
            group by tenant_id
            """  # noqa: S608 — dcol из whitelist (rr_dt|sale_dt), не польз. ввод
            ),
            {"ids": tids, "lo": start_date, "hi": end_date},
        )
    ).all()
    by_tid = {r.tenant_id: r for r in agg}
    items = []
    for tid in tids:
        r = by_tid.get(tid)
        items.append(
            {
                "tenant_id": tid,
                "name": names.get(tid, f"Кабинет {tid}"),
                "realisation": float(r.realisation) if r else 0.0,
                "sales": float(r.sales) if r else 0.0,
                "to_transfer": float(r.to_transfer) if r else 0.0,
                "sold": int(r.sold) if r else 0,
            }
        )
    items.sort(key=lambda x: x["realisation"], reverse=True)
    totals = {
        "realisation": round(sum(x["realisation"] for x in items), 2),
        "sales": round(sum(x["sales"] for x in items), 2),
        "to_transfer": round(sum(x["to_transfer"] for x in items), 2),
        "sold": sum(x["sold"] for x in items),
    }
    return {"reporting_mode": reporting_mode, "items": items, "totals": totals}


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


_ADV_TYPE = {4: "Каталог", 5: "Карточка", 6: "Поиск", 7: "Рекоменд.", 8: "Автомат.", 9: "Поиск+каталог"}
_ADV_STATUS = {4: "Готова", 7: "Завершена", 9: "Активна", 11: "Пауза"}


@router.get("/api/ad-campaigns/analytics", dependencies=[Depends(require_director_or_head)])
async def ad_campaigns_analytics(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Аналитика РК (TASK-DEV-046): свод по кампаниям из WbAdStatsDaily за период."""
    rows = (
        await session.execute(
            select(
                WbAdStatsDaily.advert_id,
                func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("views"),
                func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("clicks"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
                func.coalesce(func.sum(WbAdStatsDaily.atbs), 0).label("atbs"),
                func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("orders"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_price), 0).label("revenue"),
            )
            .where(
                WbAdStatsDaily.stat_date >= start_date,
                WbAdStatsDaily.stat_date <= end_date,
            )
            .group_by(WbAdStatsDaily.advert_id)
        )
    ).all()

    camps = {
        c.advert_id: c
        for c in (await session.execute(select(WbAdCampaign))).scalars().all()
    }

    def _f(v: Any) -> float:
        return float(v or 0)

    items = []
    for r in rows:
        views, clicks, spent = int(r.views), int(r.clicks), _f(r.spent)
        orders, revenue = int(r.orders), _f(r.revenue)
        c = camps.get(r.advert_id)
        items.append(
            {
                "advert_id": r.advert_id,
                "name": (c.name if c else None) or f"РК {r.advert_id}",
                "type": _ADV_TYPE.get(c.type if c else None, "—"),
                "status": _ADV_STATUS.get(c.status if c else None, "—"),
                "views": views,
                "clicks": clicks,
                "ctr": round(clicks / views * 100, 2) if views else 0.0,
                "cpc": round(spent / clicks, 2) if clicks else 0.0,
                "spent": round(spent, 2),
                "atbs": int(r.atbs),
                "orders": orders,
                "cr": round(orders / clicks * 100, 2) if clicks else 0.0,
                "revenue": round(revenue, 2),
                "drr": round(spent / revenue * 100, 2) if revenue else 0.0,
            }
        )
    items.sort(key=lambda x: x["spent"], reverse=True)
    tot = {
        "spent": round(sum(x["spent"] for x in items), 2),
        "revenue": round(sum(x["revenue"] for x in items), 2),
        "orders": sum(x["orders"] for x in items),
        "clicks": sum(x["clicks"] for x in items),
        "views": sum(x["views"] for x in items),
    }
    tot["drr"] = round(tot["spent"] / tot["revenue"] * 100, 2) if tot["revenue"] else 0.0
    return {"items": items, "totals": tot}


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
