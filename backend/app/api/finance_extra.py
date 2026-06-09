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

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import get_current_user

from app.db.models import (
    AppSetting,
    Cogs,
    FinanceReference,
    ManualOperation,
    MetricPlan,
    MetricPlanTarget,
    OpexCategory,
    OpexEntry,
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbCardPrice,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range
from app.services.tenant_context import get_tenant
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(tags=["finance-extra"])

# Типы операций report_detail, которые НЕ продажа/возврат — «прочие удержания».
_SALE_RETURN = ("Продажа", "Возврат")
# Core-операции, которые в TrueStats идут отдельными строками P&L и НЕ входят
# в «Прочие удержания» (логистика/хранение — отдельно, комиссия — в Продаже).
_CORE_OPS = ("Продажа", "Возврат", "Логистика", "Хранение")
# DEV-058: операция «Удержание» с обоснованием «WB Продвижение» — это РЕКЛАМА
# через финотчёт, НЕ «прочее удержание». TS не относит её к otherDeduction
# (подтверждено: строка 6 902 «WB Продвижение» → TS otherDeduction +0). Фильтруем
# по bonus_type_name ILIKE этому паттерну, чтобы «Прочие удержания» сходились с TS.
_PROMO_BONUS_LIKE = "%продвиж%"


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


@router.get("/api/manual-operations", dependencies=[Depends(require_director_or_head)])
async def list_manual_operations(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Ручные операции (TASK-DEV-048) за период."""
    rows = (
        await session.execute(
            select(ManualOperation)
            .where(ManualOperation.op_date >= start_date, ManualOperation.op_date <= end_date)
            .order_by(ManualOperation.op_date.desc(), ManualOperation.id.desc())
        )
    ).scalars().all()
    items = [
        {
            "id": r.id,
            "op_date": r.op_date.isoformat(),
            "direction": r.direction,
            "amount": float(r.amount or 0),
            "category": r.category,
            "counterparty": r.counterparty,
            "account": r.account,
            "comment": r.comment,
            "is_planned": bool(r.is_planned),
        }
        for r in rows
    ]
    # Факт (не planned) — в доход/расход; planned — в обязательства.
    income = sum(x["amount"] for x in items if x["direction"] == "income" and not x["is_planned"])
    expense = sum(x["amount"] for x in items if x["direction"] == "expense" and not x["is_planned"])
    planned_in = sum(x["amount"] for x in items if x["direction"] == "income" and x["is_planned"])
    planned_out = sum(x["amount"] for x in items if x["direction"] == "expense" and x["is_planned"])
    return {"items": items, "totals": {
        "income": round(income, 2), "expense": round(expense, 2), "net": round(income - expense, 2),
        "planned_in": round(planned_in, 2), "planned_out": round(planned_out, 2),
    }}


@router.post("/api/manual-operations", dependencies=[Depends(require_director_or_head)])
async def create_manual_operation(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    direction = str(payload.get("direction") or "")
    if direction not in {"income", "expense"}:
        raise HTTPException(400, "direction ∈ income|expense")
    try:
        op_date = date.fromisoformat(str(payload.get("op_date")))
    except Exception:
        raise HTTPException(400, "op_date YYYY-MM-DD обязателен")
    try:
        amount = float(payload.get("amount") or 0)
    except Exception:
        raise HTTPException(400, "amount должен быть числом")
    obj = ManualOperation(
        tenant_id=get_tenant(session),
        op_date=op_date,
        direction=direction,
        amount=amount,
        category=(payload.get("category") or None),
        counterparty=(payload.get("counterparty") or None),
        account=(payload.get("account") or None),
        comment=(payload.get("comment") or None),
        is_planned=bool(payload.get("is_planned")),
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return {"id": obj.id}


@router.delete("/api/manual-operations/{op_id}", dependencies=[Depends(require_director_or_head)])
async def delete_manual_operation(
    op_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(ManualOperation).where(ManualOperation.id == op_id))
    await session.commit()
    return {"status": "deleted", "id": op_id}


@router.get("/api/summary-report", dependencies=[Depends(require_director_or_head)])
async def summary_report(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сводный отчёт per-SKU 1:1 с TrueStats (TASK-DEV-039/047): реализация=retail_price
    (до СПП), продажи=retail_amount (после СПП) по rr_dt, COGS, логистика, прибыль.
    Раньше брали из /units (sale_dt) — расходилось с TS на per-SKU."""
    dcol = _date_col(reporting_mode)
    is_sale = WbReportDetail.supplier_oper_name == "Продажа"
    is_ret = WbReportDetail.supplier_oper_name == "Возврат"

    def net(col):
        return func.coalesce(
            func.sum(case((is_sale, col), else_=0)) - func.sum(case((is_ret, col), else_=0)),
            0,
        )

    rd_rows = (
        await session.execute(
            select(
                WbReportDetail.nm_id,
                net(WbReportDetail.retail_price).label("realisation"),
                net(WbReportDetail.retail_amount).label("sales"),
                net(WbReportDetail.ppvz_for_pay).label("to_transfer"),
                net(WbReportDetail.acquiring_fee).label("acquiring"),
                func.coalesce(func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0).label("sold"),
                func.coalesce(func.sum(case((is_ret, WbReportDetail.quantity), else_=0)), 0).label("ret"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("logistics"),
                func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date, WbReportDetail.nm_id.isnot(None))
            .group_by(WbReportDetail.nm_id)
        )
    ).all()

    # Per-nm аккумулятор (фин-отчёт WB). SimpleNamespace → существующий items-loop
    # читает .realisation/.sales/... без изменений.
    acc: dict[int, Any] = {}
    for r in rd_rows:
        acc[int(r.nm_id)] = SimpleNamespace(
            nm_id=int(r.nm_id),
            realisation=float(r.realisation or 0), sales=float(r.sales or 0),
            to_transfer=float(r.to_transfer or 0), acquiring=float(r.acquiring or 0),
            sold=int(r.sold), ret=int(r.ret),
            logistics=float(r.logistics or 0), storage=float(r.storage or 0),
        )

    # DEV-058: «живой хвост» — дни периода, за которые WB ещё НЕ опубликовал
    # фин-отчёт. TS заполняет их операционной оценкой; повторяем по wb_sales
    # (подтверждённые выкупы). Закрытые/опубликованные периоды НЕ затрагиваются
    # (estimated_from=None) → байт-в-байт прежнее поведение. Помечаем `estimated`.
    published_max = (
        await session.execute(
            select(func.max(func.date(dcol))).where(
                func.date(dcol) >= start_date, func.date(dcol) <= end_date
            )
        )
    ).scalar()
    est_start = (published_max + timedelta(days=1)) if published_max else start_date
    estimated_from = est_start if est_start <= end_date else None
    if estimated_from is not None:
        sret = WbSale.is_return
        srows = (
            await session.execute(
                select(
                    WbSale.nm_id,
                    # realisation (до СПП) = price_with_disc (после скидки продавца,
                    # до СПП), НЕ total_price (полная розница). sales (после СПП) =
                    # finished_price. to_transfer = for_pay. Совпадает с маппингом
                    # фин-отчёта (retail_price→realisation) по величине.
                    func.coalesce(func.sum(case((~sret, WbSale.price_with_disc), else_=0)), 0).label("realisation"),
                    func.coalesce(func.sum(case((~sret, WbSale.finished_price), else_=0)), 0).label("sales"),
                    func.coalesce(func.sum(case((~sret, WbSale.for_pay), else_=0)), 0).label("to_transfer"),
                    func.coalesce(func.sum(case((~sret, 1), else_=0)), 0).label("sold"),
                    func.coalesce(func.sum(case((sret, 1), else_=0)), 0).label("ret"),
                )
                .where(func.date(WbSale.sale_dt) >= est_start, func.date(WbSale.sale_dt) <= end_date, WbSale.nm_id.isnot(None))
                .group_by(WbSale.nm_id)
            )
        ).all()
        for e in srows:
            nm = int(e.nm_id)
            a = acc.get(nm)
            if a is None:
                a = SimpleNamespace(nm_id=nm, realisation=0.0, sales=0.0, to_transfer=0.0,
                                    acquiring=0.0, sold=0, ret=0, logistics=0.0, storage=0.0)
                acc[nm] = a
            # Операционный хвост: реализация/продажи/к перечислению/выкупы.
            # Логистика/хранение/эквайринг в выписке выкупов отсутствуют (0).
            a.realisation += float(e.realisation or 0)
            a.sales += float(e.sales or 0)
            a.to_transfer += float(e.to_transfer or 0)
            a.sold += int(e.sold)
            a.ret += int(e.ret)

    rows = list(acc.values())
    nm_ids = list(acc.keys())
    # COGS — себестоимость, ДЕЙСТВОВАВШАЯ в периоде (valid_from <= end_date),
    # последняя из таких. DEV-060: важно для versioning — TS меняет себестоимость
    # датой (напр. −11₽/шт с 25.05); брать абсолютный latest ломало бы прошлые
    # недели (18-24 должна остаться на старой цене). Берём версию as-of периода.
    cogs_map: dict[int, float] = {}
    if nm_ids:
        crows = (
            await session.execute(
                select(Cogs.nm_id, Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub, Cogs.valid_from)
                .where(Cogs.nm_id.in_(nm_ids), Cogs.valid_from <= end_date)
                .order_by(Cogs.nm_id, Cogs.valid_from.desc())
            )
        ).all()
        for c in crows:
            if int(c.nm_id) not in cogs_map:
                cogs_map[int(c.nm_id)] = float(c.cost_rub or 0) + float(c.packaging_rub or 0) + float(c.fulfillment_rub or 0)
    # Реклама per nm.
    ad_map: dict[int, float] = {}
    if nm_ids:
        arows = (
            await session.execute(
                select(WbAdStatsDaily.nm_id, func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0))
                .where(WbAdStatsDaily.stat_date >= start_date, WbAdStatsDaily.stat_date <= end_date, WbAdStatsDaily.nm_id.isnot(None))
                .group_by(WbAdStatsDaily.nm_id)
            )
        ).all()
        ad_map = {int(n): float(s or 0) for n, s in arows}
    # Товары (имена/фото).
    prod_map: dict[int, Any] = {}
    if nm_ids:
        prows = (
            await session.execute(
                select(Product.nm_id, Product.vendor_code, Product.brand, Product.subject, Product.photo_url).where(Product.nm_id.in_(nm_ids))
            )
        ).all()
        prod_map = {int(p.nm_id): p for p in prows}
    # Ставка налога (АУСН доход) из настроек tenant.
    tid = get_tenant(session)
    tr_stmt = select(AppSetting.value).where(AppSetting.key == "tax_rate")
    if tid is not None:
        tr_stmt = tr_stmt.where(AppSetting.tenant_id == tid)
    tax_rate = float((await session.execute(tr_stmt)).scalar() or 0)

    # Компанейский OPEX (операционный) за период → аллокация по SKU пропорц.
    # реализации (как TS распределяет expense на товары). DEV-052.
    opex_total = float(
        (
            await session.execute(
                select(func.coalesce(func.sum(OpexEntry.amount), 0))
                .join(OpexCategory, OpexEntry.category_id == OpexCategory.id)
                .where(
                    OpexEntry.entry_date >= start_date,
                    OpexEntry.entry_date <= end_date,
                    OpexCategory.kind == "expense",
                    OpexCategory.in_operating.is_(True),
                )
            )
        ).scalar()
        or 0
    )
    total_realisation = sum(float(r.realisation or 0) for r in rows) or 1.0

    # «Прочие удержания» (deduction/приёмка/доплаты, БЕЗ штрафов), «Штрафы»
    # (penalty) и «Реклама из финотчёта» (WB Продвижение) за период — DEV-058.
    # Прочие удержания вычитаются из прибыли (TS-parity: TS otherDeduction входит
    # в profit), аллокация по SKU пропорц. реализации (как OPEX). Штрафы — отдельной
    # плиткой, в прибыль НЕ входят. «WB Продвижение» исключаем из прочих удержаний
    # (TS относит её к рекламе, не к otherDeduction) — see _PROMO_BONUS_LIKE.
    is_promo = func.coalesce(WbReportDetail.bonus_type_name, "").ilike(_PROMO_BONUS_LIKE)
    ded_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((~is_promo, WbReportDetail.deduction), else_=0)), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.paid_acceptance), 0).label("acceptance"),
                func.coalesce(func.sum(WbReportDetail.additional_payment), 0).label("additional"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(case((is_promo, WbReportDetail.deduction), else_=0)), 0).label("promo_ad"),
                # Компенсации (TS `compensation`): деньги, которые WB доплачивает по
                # non-core операциям («Добровольная компенсация», «Возмещение…») —
                # сидят в ppvz_for_pay этих строк (не в Продаже/Возврате). ДОБАВЛЯЮТСЯ
                # к прибыли. Сверено 25-31: 1905 = TS compensation 1904.72.
                func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0).label("comp_ppvz"),
            ).where(
                func.date(dcol) >= start_date,
                func.date(dcol) <= end_date,
                WbReportDetail.supplier_oper_name.notin_(_CORE_OPS),
            )
        )
    ).one()
    # «Прочие удержания» (otherDeduction TS) — вычитаются: удержание(без промо) + приёмка.
    prochie_total = float(ded_row.deduction or 0) + float(ded_row.acceptance or 0)
    acceptance_total = float(ded_row.acceptance or 0)  # «Плат. приемка» отдельной плиткой
    fines_total = float(ded_row.penalty or 0)
    promo_ad_total = float(ded_row.promo_ad or 0)  # WB Продвижение из финотчёта (как TS — не в прибыль здесь)
    # Компенсации — добавляются к прибыли (доплаты + ppvz компенсационных операций).
    compensation_total = float(ded_row.comp_ppvz or 0) + float(ded_row.additional or 0)
    # Детализация логистики по 5 категориям WB (DEV-060): дискриминатор —
    # bonus_type_name на строках «Логистика» (К клиенту при отмене/продаже,
    # От клиента при отмене/возврате, Возврат брака). Сверено с TS «в рубль».
    log_rows = (
        await session.execute(
            select(
                func.coalesce(WbReportDetail.bonus_type_name, "—").label("cat"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("amt"),
            )
            .where(
                func.date(dcol) >= start_date,
                func.date(dcol) <= end_date,
                WbReportDetail.supplier_oper_name == "Логистика",
            )
            .group_by(WbReportDetail.bonus_type_name)
        )
    ).all()
    logistics_breakdown = [
        {"category": r.cat, "amount": round(float(r.amt or 0), 2)}
        for r in log_rows if abs(float(r.amt or 0)) >= 0.005
    ]
    logistics_breakdown.sort(key=lambda x: abs(x["amount"]), reverse=True)

    # Возвраты ₽ (gross retail возвратов) — для плитки «Возвраты».
    returns_rub = float(
        (
            await session.execute(
                select(func.coalesce(func.sum(WbReportDetail.retail_price), 0)).where(
                    func.date(dcol) >= start_date,
                    func.date(dcol) <= end_date,
                    WbReportDetail.supplier_oper_name == "Возврат",
                )
            )
        ).scalar()
        or 0
    )

    def _f(v: Any) -> float:
        return float(v or 0)

    items = []
    for r in rows:
        nm = int(r.nm_id)
        sales = _f(r.sales)
        # net-выкупы (Продажа − Возврат) — как TS totalSales; COGS на них же.
        net_sold = int(r.sold) - int(r.ret)
        cogs = cogs_map.get(nm, 0.0) * net_sold
        ad = ad_map.get(nm, 0.0)
        tax = sales * tax_rate / 100.0
        share = _f(r.realisation) / total_realisation
        opex = opex_total * share
        prochie = prochie_total * share
        compensation = compensation_total * share
        # прибыль = к перечислению − логистика − хранение − COGS − налог −
        # реклама − OPEX − прочие удержания + компенсации (TS-parity, account 25143).
        # Штрафы (penalty) — отдельно, в прибыль НЕ входят (как TS).
        profit = _f(r.to_transfer) - _f(r.logistics) - _f(r.storage) - cogs - tax - ad - opex - prochie + compensation
        p = prod_map.get(nm)
        items.append({
            "nm_id": nm,
            "vendor_code": p.vendor_code if p else None,
            "brand": p.brand if p else None,
            "subject": p.subject if p else None,
            "photo_url": p.photo_url if p else None,
            "realisation": round(_f(r.realisation), 2),
            "sales": round(sales, 2),
            "to_transfer": round(_f(r.to_transfer), 2),
            "commission": round(sales - _f(r.to_transfer) - _f(r.acquiring), 2),
            "acquiring": round(_f(r.acquiring), 2),
            "logistics": round(_f(r.logistics), 2),
            "storage": round(_f(r.storage), 2),
            "cogs": round(cogs, 2),
            "ad": round(ad, 2),
            "tax": round(tax, 2),
            "opex": round(opex, 2),
            "deductions": round(prochie, 2),
            "sold": net_sold,
            "returned": int(r.ret),
            "profit": round(profit, 2),
            "margin_pct": round(profit / sales * 100, 2) if sales > 0 else 0.0,
            "roi_pct": round(profit / cogs * 100, 2) if cogs > 0 else 0.0,
        })
    items.sort(key=lambda x: x["realisation"], reverse=True)
    # Заказы / % выкупа — preliminary (по order_dt, как TS «Заказы»=ordersCount).
    # DEV-058: при частичном покрытии funnel compute_dashboard теперь сам
    # делает fallback на полный wb_orders (фикс _funnel_covers_period).
    pre = await compute_dashboard(session, period_from_range(start_date, end_date), mode="preliminary")
    pmap = {k["key"]: k.get("value") for k in pre.get("kpis", [])}

    # Остатки + капитализация (DEV-060 Phase 2): последний снапшот WbStockSnapshot.
    # Остатки(шт) = склад + в пути к/от клиента (как TS stockBalance). Капитализация
    # по себес = Σ qty×cogs_unit; по рознице = Σ qty×price(после скидки).
    last_snap = (
        await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
    ).scalar()
    stock_wh = stock_to = stock_from = 0
    cap_cost = cap_price = 0.0
    if last_snap is not None:
        srows = (
            await session.execute(
                select(
                    WbStockSnapshot.nm_id,
                    func.coalesce(func.sum(WbStockSnapshot.quantity), 0).label("qty"),
                    func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("to_c"),
                    func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("from_c"),
                )
                .where(WbStockSnapshot.snapshot_dt == last_snap)
                .group_by(WbStockSnapshot.nm_id)
            )
        ).all()
        # Капитализация по рознице ≈ остаток × витринная цена покупателя (buyer_price,
        # после СПП) из wb_card_price (миграция 0069). NB: точного паритета с TS
        # capitalizationByPrice нет — TS юзает внутреннюю «set price» между ценой до/
        # после СПП, а сама плитка завязана на ТЕКУЩИЙ снапшот остатков (наш ≠ снапшот
        # TS). basic_price (RRP до скидок) завышает в ~2-3× — НЕ используем.
        snap_nm0 = [int(s.nm_id) for s in srows if s.nm_id]
        price_map: dict[int, float] = {}
        if snap_nm0:
            prows = (
                await session.execute(
                    select(WbCardPrice.nm_id, WbCardPrice.buyer_price).where(
                        WbCardPrice.nm_id.in_(snap_nm0), WbCardPrice.buyer_price.isnot(None)
                    )
                )
            ).all()
            price_map = {int(n): float(p or 0) for n, p in prows}
        # COGS as-of сегодня (для капитализации берём текущую себестоимость).
        cogs_now: dict[int, float] = {}
        snap_nm = [int(s.nm_id) for s in srows if s.nm_id]
        if snap_nm:
            ccur = (
                await session.execute(
                    select(Cogs.nm_id, Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
                    .where(Cogs.nm_id.in_(snap_nm), Cogs.valid_from <= end_date)
                    .order_by(Cogs.nm_id, Cogs.valid_from.desc())
                )
            ).all()
            for c in ccur:
                if int(c.nm_id) not in cogs_now:
                    cogs_now[int(c.nm_id)] = float(c.cost_rub or 0) + float(c.packaging_rub or 0) + float(c.fulfillment_rub or 0)
        for s in srows:
            qty = int(s.qty)
            stock_wh += qty
            stock_to += int(s.to_c)
            stock_from += int(s.from_c)
            total_units = qty + int(s.to_c) + int(s.from_c)
            cap_cost += total_units * cogs_now.get(int(s.nm_id), 0.0)
            cap_price += total_units * price_map.get(int(s.nm_id), 0.0)
    stock_total = stock_wh + stock_to + stock_from
    period_days = (end_date - start_date).days + 1

    def _s(f: str) -> float:
        return round(sum(x[f] for x in items), 2)

    realisation_t, sales_t, cogs_t = _s("realisation"), _s("sales"), _s("cogs")
    logistics_t, storage_t = _s("logistics"), _s("storage")
    commission_t, acquiring_t = _s("commission"), _s("acquiring")
    profit_t, opex_t = _s("profit"), _s("opex")
    ad_t = _s("ad")
    sold_t = sum(x["sold"] for x in items)
    rev_gross = pmap.get("revenue_gross") or 0
    profit_wo_opex_t = round(profit_t + opex_t, 2)
    R = realisation_t or 1.0  # знаменатель долей = реализация (как TS *Share)

    def _pct(v: float) -> float:
        return round(v / R * 100, 2)

    tot = {
        "realisation": realisation_t,
        "sales": sales_t,
        "to_transfer": _s("to_transfer"),
        "cogs": cogs_t,
        "cogs_pct": _pct(cogs_t),  # costOfSalesShare
        "ad": ad_t,
        "tax": _s("tax"),
        "tax_pct": _pct(_s("tax")),
        "tax_base": sales_t,  # наша налоговая база = продажи (×ставку)
        "opex": opex_t,
        "opex_pct": _pct(opex_t),
        "profit": profit_t,
        "profit_wo_opex": profit_wo_opex_t,
        # Маржа = прибыль / реализация (как TS marginality), НЕ /продажи.
        "margin_pct": round(profit_t / R * 100, 2),
        "margin_wo_opex_pct": round(profit_wo_opex_t / R * 100, 2),
        "sold": sold_t,
        "returned": sum(x["returned"] for x in items),
        "returns_rub": round(returns_rub, 2),
        "logistics": logistics_t,
        "logistics_pct": _pct(logistics_t),  # logisticsShare
        "storage": storage_t,
        "storage_pct": _pct(storage_t),  # storageShare
        # «Комиссия» у TS = комиссия WB + эквайринг (подтверждено сверкой).
        "commission": round(commission_t + acquiring_t, 2),
        "commission_pct": _pct(commission_t + acquiring_t),  # commissionShare
        "acquiring": acquiring_t,
        "roi_pct": round(profit_t / cogs_t * 100, 2) if cogs_t else 0.0,
        # «Прочие удержания» — операционные (БЕЗ штрафов, вычитаются из прибыли);
        # «Штрафы» — penalty; «Плат. приемка»; «Компенсации» (+ к прибыли). DEV-060.
        "deductions": round(prochie_total, 2),
        "deductions_pct": _pct(prochie_total),
        "fines": round(fines_total, 2),
        "acceptance": round(acceptance_total, 2),
        "acceptance_pct": _pct(acceptance_total),
        "compensation": round(compensation_total, 2),
        "compensation_pct": _pct(compensation_total),
        "promo_ad": round(promo_ad_total, 2),  # WB Продвижение из финотчёта (справочно)
        "orders_count": pmap.get("orders"),
        "orders_sum": round(rev_gross, 2),
        # Выкуп% = выкуплено(₽)/заказано(₽) — как TS averageRedemption (НЕ funnel count).
        "buyout_pct": round(sales_t / rev_gross * 100, 2) if rev_gross else 0.0,
        # ДРР = реклама/реализация; ДРРз = реклама/заказы (как TS drr / drrz).
        "drr_pct": _pct(ad_t),
        "drrz_pct": round(ad_t / rev_gross * 100, 2) if rev_gross else 0.0,
        # Средние (как TS averages).
        "avg_price_sale": round(sales_t / sold_t, 2) if sold_t else 0.0,
        "avg_price_before_spp": round(realisation_t / sold_t, 2) if sold_t else 0.0,
        "avg_logistics_per_unit": round(logistics_t / sold_t, 2) if sold_t else 0.0,
        "avg_profit_per_unit": round(profit_t / sold_t, 2) if sold_t else 0.0,
        # Остатки + капитализация + оборачиваемость (DEV-060 Phase 2, как TS).
        "stock_total": stock_total,
        "stock_wh": stock_wh,           # На складах МП
        "stock_to_client": stock_to,    # В пути к клиентам
        "stock_from_client": stock_from,  # В пути от клиентов
        "cap_by_cost": round(cap_cost, 2),    # Капитализация по себестоимости
        "cap_by_price": round(cap_price, 2),  # Капитализация по рознице
        # Оборачиваемость (дн.) = остаток / (продано|заказано в день).
        "turnover_sales_days": round(stock_total / (sold_t / period_days), 2) if sold_t else None,
        "turnover_orders_days": round(stock_total / ((pmap.get("orders") or 0) / period_days), 2) if pmap.get("orders") else None,
        # GMROI у TS = null на недельном окне (нужен годовой расчёт) — отдаём null.
        "gmroi": None,
        # Итоговое вознаграждение ВБ = что WB удержал = реализация − к перечислению.
        "wb_final_reward": round(realisation_t - _s("to_transfer"), 2),
        # «Мои склады» (off-platform) — у этого продавца 0 (как TS).
        "own_stock_units": 0,
        "own_stock_cap": 0.0,
    }
    return {
        "reporting_mode": reporting_mode,
        "tax_rate": tax_rate,
        "items": items,
        "totals": tot,
        # Детализация логистики (5 категорий WB) — для выпадашки на плитке.
        "logistics_breakdown": [
            {**b, "pct": _pct(b["amount"])} for b in logistics_breakdown
        ],
        # Фин-отчёт WB опубликован по этот день включительно; дни после —
        # операционная оценка по выкупам (estimated_from). None = весь период
        # опубликован (закрытая неделя, без оценки).
        "published_through": published_max.isoformat() if published_max else None,
        "estimated_from": estimated_from.isoformat() if estimated_from else None,
    }


# Метрики, доступные для план-факта (slug = ключ KPI дашборда → человекочит. label).
_PLAN_METRICS = {
    "revenue_gross": "Выручка (заказы)",
    "orders": "Заказы",
    "returns": "Возвраты",
    "buyout_pct": "Выкуп %",
    "net_profit": "Чистая прибыль",
    "margin_pct": "Маржа %",
    "drr_pct": "ДРР %",
    "ad_cost": "Реклама",
}


async def _plan_fact_values(session: AsyncSession, started: date, finished: date) -> dict[str, float]:
    """KPI-факт за период плана. Заказы/выручка-заказов/выкуп% — preliminary (по
    order_dt, как TS «Заказы»=ordersCount); прибыль/маржа/ДРР/возвраты — final
    (financial/rr_dt). DEV-053."""
    period = period_from_range(started, finished)
    fin = await compute_dashboard(session, period, mode="final", reporting_mode="financial")
    pre = await compute_dashboard(session, period, mode="preliminary")
    fmap = {k["key"]: k.get("value") for k in fin.get("kpis", [])}
    pmap = {k["key"]: k.get("value") for k in pre.get("kpis", [])}
    for k in ("orders", "revenue_gross", "buyout_pct"):
        if pmap.get(k) is not None:
            fmap[k] = pmap[k]
    return fmap


@router.get("/api/metric-plans", dependencies=[Depends(require_director_or_head)])
async def list_metric_plans(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """План-факт по метрикам (TASK-DEV-050) — копия TrueStats «План-факт»."""
    plans = (
        await session.execute(select(MetricPlan).order_by(MetricPlan.started_at.desc()))
    ).scalars().all()
    targets_all = (await session.execute(select(MetricPlanTarget))).scalars().all()
    by_plan: dict[int, list[Any]] = {}
    for t in targets_all:
        by_plan.setdefault(t.plan_id, []).append(t)

    items = []
    for p in plans:
        fact = await _plan_fact_values(session, p.started_at, p.finished_at)
        metrics = []
        for t in by_plan.get(p.id, []):
            f = fact.get(t.metric_slug)
            pv = float(t.plan_value or 0)
            metrics.append({
                "metric_slug": t.metric_slug,
                "label": _PLAN_METRICS.get(t.metric_slug, t.metric_slug),
                "plan": pv,
                "fact": round(float(f), 2) if f is not None else None,
                "done_pct": round(float(f) / pv * 100, 1) if (f is not None and pv) else None,
            })
        items.append({
            "id": p.id,
            "title": p.title,
            "started_at": p.started_at.isoformat(),
            "finished_at": p.finished_at.isoformat(),
            "metrics": metrics,
        })
    return {"available_metrics": _PLAN_METRICS, "items": items}


@router.post("/api/metric-plans", dependencies=[Depends(require_director_or_head)])
async def create_metric_plan(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title обязателен")
    try:
        started = date.fromisoformat(str(payload.get("started_at")))
        finished = date.fromisoformat(str(payload.get("finished_at")))
    except Exception:
        raise HTTPException(400, "started_at/finished_at YYYY-MM-DD обязательны")
    tid = get_tenant(session)
    plan = MetricPlan(tenant_id=tid, title=title, started_at=started, finished_at=finished)
    session.add(plan)
    await session.flush()
    for t in payload.get("targets") or []:
        slug = str(t.get("metric_slug") or "")
        if slug not in _PLAN_METRICS:
            continue
        session.add(MetricPlanTarget(
            tenant_id=tid, plan_id=plan.id, metric_slug=slug, plan_value=float(t.get("plan_value") or 0),
        ))
    await session.commit()
    return {"id": plan.id}


@router.delete("/api/metric-plans/{plan_id}", dependencies=[Depends(require_director_or_head)])
async def delete_metric_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(MetricPlanTarget).where(MetricPlanTarget.plan_id == plan_id))
    await session.execute(sa_delete(MetricPlan).where(MetricPlan.id == plan_id))
    await session.commit()
    return {"status": "deleted", "id": plan_id}


@router.get("/api/cashflow-calendar", dependencies=[Depends(require_director_or_head)])
async def cashflow_calendar(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """ДДС-копия TrueStats (TASK-DEV-049): дневной календарь движения денег из
    ручных операций (ManualOperation). Структура как у TS /v1/cashflow/
    payment-calendar: per-day income/expense/balance/обязательства. Обязательства
    (planned) пока 0 — у нас нет флага планируемых операций."""
    rows = (
        await session.execute(
            select(
                ManualOperation.op_date,
                ManualOperation.direction,
                ManualOperation.is_planned,
                func.coalesce(func.sum(ManualOperation.amount), 0).label("amt"),
            )
            .where(ManualOperation.op_date >= start_date, ManualOperation.op_date <= end_date)
            .group_by(ManualOperation.op_date, ManualOperation.direction, ManualOperation.is_planned)
        )
    ).all()
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r.op_date.isoformat()
        slot = by_day.setdefault(d, {"income": 0.0, "expense": 0.0, "obl_in": 0.0, "obl_out": 0.0})
        amt = float(r.amt or 0)
        if r.is_planned:
            # planned → обязательство (как TS obligationReceivable/Payable), вне баланса
            slot["obl_in" if r.direction == "income" else "obl_out"] += amt
        else:
            slot["income" if r.direction == "income" else "expense"] += amt

    # Полный список дней с накопительным балансом (только факт, planned — отдельно).
    out = []
    balance = 0.0
    cur = start_date
    from datetime import timedelta as _td

    while cur <= end_date:
        d = cur.isoformat()
        slot = by_day.get(d, {"income": 0.0, "expense": 0.0, "obl_in": 0.0, "obl_out": 0.0})
        balance += slot["income"] - slot["expense"]
        out.append(
            {
                "date": d,
                "income": round(slot["income"], 2),
                "expense": round(slot["expense"], 2),
                "balance": round(balance, 2),
                "obligation_receivable": round(slot["obl_in"], 2),
                "obligation_payable": round(slot["obl_out"], 2),
            }
        )
        cur = cur + _td(days=1)
    totals = {
        "income": round(sum(x["income"] for x in out), 2),
        "expense": round(sum(x["expense"] for x in out), 2),
        "balance": round(balance, 2),
        "obligation_receivable": round(sum(x["obligation_receivable"] for x in out), 2),
        "obligation_payable": round(sum(x["obligation_payable"] for x in out), 2),
    }
    return {"data": out, "totals": totals}


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

    # DEV-058 «живой хвост»: дни, за которые WB ещё не опубликовал фин-отчёт,
    # заполняем операционной оценкой по wb_sales (как /summary-report). Закрытые
    # периоды → estimated_from=None, поведение не меняется.
    published_max = (
        await session.execute(
            text(
                f"select max({dcol}::date) from wb_report_detail "
                f"where tenant_id = any(:ids) and {dcol}::date between :lo and :hi"  # noqa: S608
            ),
            {"ids": tids, "lo": start_date, "hi": end_date},
        )
    ).scalar()
    est_start = (published_max + timedelta(days=1)) if published_max else start_date
    estimated_from = est_start if est_start <= end_date else None
    tail_by_tid: dict[int, Any] = {}
    if estimated_from is not None:
        tail = (
            await session.execute(
                text(
                    """
                select tenant_id,
                  coalesce(sum(case when not is_return then price_with_disc else 0 end),0) realisation,
                  coalesce(sum(case when not is_return then finished_price else 0 end),0) sales,
                  coalesce(sum(case when not is_return then for_pay else 0 end),0) to_transfer,
                  coalesce(sum(case when not is_return then 1 else 0 end),0) sold
                from wb_sales
                where tenant_id = any(:ids) and sale_dt::date between :est and :hi
                group by tenant_id
                """
                ),
                {"ids": tids, "est": est_start, "hi": end_date},
            )
        ).all()
        tail_by_tid = {r.tenant_id: r for r in tail}

    items = []
    for tid in tids:
        r = by_tid.get(tid)
        t = tail_by_tid.get(tid)
        items.append(
            {
                "tenant_id": tid,
                "name": names.get(tid, f"Кабинет {tid}"),
                "realisation": (float(r.realisation) if r else 0.0) + (float(t.realisation) if t else 0.0),
                "sales": (float(r.sales) if r else 0.0) + (float(t.sales) if t else 0.0),
                "to_transfer": (float(r.to_transfer) if r else 0.0) + (float(t.to_transfer) if t else 0.0),
                "sold": (int(r.sold) if r else 0) + (int(t.sold) if t else 0),
            }
        )
    items.sort(key=lambda x: x["realisation"], reverse=True)
    totals = {
        "realisation": round(sum(x["realisation"] for x in items), 2),
        "sales": round(sum(x["sales"] for x in items), 2),
        "to_transfer": round(sum(x["to_transfer"] for x in items), 2),
        "sold": sum(x["sold"] for x in items),
    }
    return {
        "reporting_mode": reporting_mode,
        "items": items,
        "totals": totals,
        "published_through": published_max.isoformat() if published_max else None,
        "estimated_from": estimated_from.isoformat() if estimated_from else None,
    }


@router.get("/api/deductions", dependencies=[Depends(require_director_or_head)])
async def get_deductions(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """«Прочие удержания» — non-core удержания/доплаты (удержания, приёмка,
    доплаты/возмещения, Джем/транзит). По доке TrueStats сюда НЕ входят логистика
    / хранение / комиссия — отдельными строками P&L. DEV-058: штрафы (penalty)
    выделены отдельно (`fines`/`fines_total`) и НЕ входят в headline `total` —
    как в TS, где «Прочие удержания» = операционные удержания без штрафов, а
    штрафы показываются отдельной строкой и не вычитаются из прибыли с прочими.
    DEV-058: «WB Продвижение» (реклама через финотчёт) выделена в `promo` и НЕ
    входит в headline `total` — TS относит её к рекламе, не к otherDeduction."""
    dcol = _date_col(reporting_mode)
    is_promo = func.coalesce(WbReportDetail.bonus_type_name, "").ilike(_PROMO_BONUS_LIKE)
    rows = (
        await session.execute(
            select(
                WbReportDetail.supplier_oper_name.label("op"),
                func.count().label("n"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(case((~is_promo, WbReportDetail.deduction), else_=0)), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.paid_acceptance), 0).label("acceptance"),
                func.coalesce(func.sum(WbReportDetail.additional_payment), 0).label("additional"),
                func.coalesce(func.sum(case((is_promo, WbReportDetail.deduction), else_=0)), 0).label("promo"),
            )
            .where(
                func.date(dcol) >= start_date,
                func.date(dcol) <= end_date,
                WbReportDetail.supplier_oper_name.notin_(_CORE_OPS),
            )
            .group_by(WbReportDetail.supplier_oper_name)
        )
    ).all()

    def _f(v: Any) -> float:
        return float(v or 0)

    items = []
    for r in rows:
        # Операционное удержание (БЕЗ штрафов и БЕЗ WB Продвижения): удержание +
        # приёмка − доплаты.
        amount = _f(r.deduction) + _f(r.acceptance) - _f(r.additional)
        fines = _f(r.penalty)
        promo = _f(r.promo)
        if abs(amount) < 0.005 and abs(fines) < 0.005 and abs(promo) < 0.005 and int(r.n) == 0:
            continue
        items.append(
            {
                "operation": r.op,
                "count": int(r.n),
                "penalty": fines,
                "deduction": _f(r.deduction),
                "acceptance": _f(r.acceptance),
                "additional": _f(r.additional),
                # «total» — операционное удержание без штрафа и без WB Продвижения
                # (headline TS); «fines» — штраф; «promo» — WB Продвижение (реклама).
                "total": round(amount, 2),
                "fines": round(fines, 2),
                "promo": round(promo, 2),
            }
        )
    items.sort(key=lambda x: abs(x["total"]) + abs(x["fines"]) + abs(x["promo"]), reverse=True)
    total = round(sum(x["total"] for x in items), 2)
    fines_total = round(sum(x["fines"] for x in items), 2)
    promo_total = round(sum(x["promo"] for x in items), 2)
    return {"reporting_mode": reporting_mode, "items": items, "total": total, "fines_total": fines_total, "promo_total": promo_total}


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
            "bonus_type_name": r.bonus_type_name,
            "doc_type_name": r.doc_type_name,
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
