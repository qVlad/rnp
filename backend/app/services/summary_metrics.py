"""Движок «Сводного отчёта» / «Исходной таблицы» (TASK-DEV-039/047 → DEV-094).

Вынесен из api/finance_extra.py:summary_report, чтобы переиспользоваться:
- GET /api/summary-report (страница «Сводный отчёт» + «Исходная таблица» на
  дашборде, ~55 колонок per-SKU);
- GET /api/dashboard/extended-kpis (TS-паритет: 37 KPI-плиток);
- GET /api/summary-report/export.xlsx.

Методология (сверено с TrueStats копейка-в-копейку, RECON_GUIDE):
реализация=retail_price (до СПП), продажи=retail_amount (после СПП), период по
rr_dt (financial) либо sale_dt (operational); «живой хвост» после последней
опубликованной недели — операционная оценка по wb_sales (estimated_from).

DEV-094 добавляет: штрафы/приёмка/компенсации/вознаграждение ВБ per-SKU,
номинальная комиссия (WbTariffCommission), заказы и % выкупа per-SKU, цены и
динамика, остатки 4 вида + капитализации + оборачиваемость + GMROI per-SKU,
ABC по прибыли и по выручке, доля выручки, ДРР бонусов / общая, own-склады
из off_platform.summary, группировка по склейке (imt), дельты к прошлому
равному периоду (include_prev).
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    Cogs,
    OpexCategory,
    OpexEntry,
    Product,
    ProductGroup,
    ProductGroupAssignment,
    Tenant,
    WbAdStatsDaily,
    WbCardPrice,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
    WbTariffCommission,
)
from app.services.tenant_context import get_tenant

# Типы операций report_detail: core — отдельные строки P&L, не «прочие удержания».
_CORE_OPS = ("Продажа", "Возврат", "Логистика", "Хранение")
# «Удержание» с обоснованием «WB Продвижение» — реклама через финотчёт (DEV-058).
_PROMO_BONUS_LIKE = "%продвиж%"


def _date_col(reporting_mode: str):
    return WbReportDetail.rr_dt if reporting_mode == "financial" else WbReportDetail.sale_dt


def _f(v: Any) -> float:
    return float(v or 0)


async def build_summary_report(
    session: AsyncSession,
    *,
    start_date: date,
    end_date: date,
    reporting_mode: str = "financial",
    nm_scope: set[int] | None = None,
    group_by: str = "sku",  # sku | imt (склейки, DEV-094)
    include_prev: bool = False,  # дельты к предыдущему равному периоду
) -> dict[str, Any]:
    nm_pred = [WbReportDetail.nm_id.in_(nm_scope)] if nm_scope is not None else []
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
                net(WbReportDetail.ppvz_vw).label("vw"),
                func.coalesce(func.sum(case((is_sale, WbReportDetail.quantity), else_=0)), 0).label("sold"),
                func.coalesce(func.sum(case((is_ret, WbReportDetail.quantity), else_=0)), 0).label("ret"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("logistics"),
                func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date, WbReportDetail.nm_id.isnot(None), *nm_pred)
            .group_by(WbReportDetail.nm_id)
        )
    ).all()

    acc: dict[int, Any] = {}
    for r in rd_rows:
        acc[int(r.nm_id)] = SimpleNamespace(
            nm_id=int(r.nm_id),
            realisation=_f(r.realisation), sales=_f(r.sales),
            to_transfer=_f(r.to_transfer), acquiring=_f(r.acquiring),
            vw=_f(r.vw),
            sold=int(r.sold), ret=int(r.ret),
            logistics=_f(r.logistics), storage=_f(r.storage),
        )

    # DEV-058: «живой хвост» — дни без опубликованного финотчёта → оценка по
    # wb_sales (подтверждённые выкупы). Закрытые недели не затрагиваются.
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
        srows_est = (
            await session.execute(
                select(
                    WbSale.nm_id,
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
        for e in srows_est:
            nm = int(e.nm_id)
            a = acc.get(nm)
            if a is None:
                a = SimpleNamespace(nm_id=nm, realisation=0.0, sales=0.0, to_transfer=0.0,
                                    acquiring=0.0, vw=0.0, sold=0, ret=0, logistics=0.0, storage=0.0)
                acc[nm] = a
            a.realisation += _f(e.realisation)
            a.sales += _f(e.sales)
            a.to_transfer += _f(e.to_transfer)
            a.sold += int(e.sold)
            a.ret += int(e.ret)

    # Заказы per nm за период — DEV-094. Приоритетный источник — ВОРОНКА
    # (wb_funnel_daily): TS «Заказы» = ordersCount Воронки (включает рассрочку),
    # сверено с живым TS 22-28.06 копейка-в-копейку. Для SKU без funnel-строк
    # (Воронка копится с 22.05.2026) — fallback wb_orders («Лента»).
    # Терминальный % выкупа (buyouts/(buyouts+cancels)) — тоже отсюда.
    from app.db.models import WbFunnelDaily  # noqa: WPS433

    funnel_preds = [WbFunnelDaily.dt >= start_date, WbFunnelDaily.dt <= end_date]
    if nm_scope is not None:
        funnel_preds.append(WbFunnelDaily.nm_id.in_(nm_scope))
    fun_rows = (
        await session.execute(
            select(
                WbFunnelDaily.nm_id,
                func.coalesce(func.sum(WbFunnelDaily.orders_count), 0).label("cnt"),
                func.coalesce(func.sum(WbFunnelDaily.orders_sum_rub), 0).label("amt"),
                func.coalesce(func.sum(WbFunnelDaily.buyouts_count), 0).label("b"),
                func.coalesce(func.sum(WbFunnelDaily.cancel_count), 0).label("c"),
            )
            .where(*funnel_preds)
            .group_by(WbFunnelDaily.nm_id)
        )
    ).all()
    orders_map: dict[int, tuple[int, float]] = {
        int(r.nm_id): (int(r.cnt), _f(r.amt)) for r in fun_rows if r.nm_id
    }
    buyout_map: dict[int, float | None] = {
        int(r.nm_id): (int(r.b) / (int(r.b) + int(r.c)) * 100 if (int(r.b) + int(r.c)) > 0 else None)
        for r in fun_rows if r.nm_id
    }
    buyout_b_total = sum(int(r.b) for r in fun_rows)
    buyout_c_total = sum(int(r.c) for r in fun_rows)

    orders_preds = [
        func.date(WbOrder.order_dt) >= start_date,
        func.date(WbOrder.order_dt) <= end_date,
        WbOrder.is_cancel.is_(False),
    ]
    if nm_scope is not None:
        orders_preds.append(WbOrder.nm_id.in_(nm_scope))
    orows = (
        await session.execute(
            select(
                WbOrder.nm_id,
                func.count(WbOrder.srid).label("cnt"),
                func.coalesce(func.sum(func.coalesce(WbOrder.price_with_disc, WbOrder.total_price)), 0).label("amt"),
            )
            .where(*orders_preds)
            .group_by(WbOrder.nm_id)
        )
    ).all()
    for o in orows:
        if o.nm_id and int(o.nm_id) not in orders_map:
            orders_map[int(o.nm_id)] = (int(o.cnt), _f(o.amt))
    for nm in orders_map:
        if nm not in acc:
            acc[nm] = SimpleNamespace(nm_id=nm, realisation=0.0, sales=0.0, to_transfer=0.0,
                                      acquiring=0.0, vw=0.0, sold=0, ret=0, logistics=0.0, storage=0.0)

    rows = list(acc.values())
    nm_ids = list(acc.keys())

    # COGS as-of конца периода (versioning DEV-060).
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
                cogs_map[int(c.nm_id)] = _f(c.cost_rub) + _f(c.packaging_rub) + _f(c.fulfillment_rub)

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
        ad_map = {int(n): _f(s) for n, s in arows}

    # Товары (имена/фото/категория/склейка/tenant) + группы + имена кабинетов.
    prod_map: dict[int, Any] = {}
    if nm_ids:
        prows = (
            await session.execute(
                select(
                    Product.nm_id, Product.vendor_code, Product.brand, Product.subject,
                    Product.category, Product.photo_url, Product.imt_id, Product.tenant_id,
                ).where(Product.nm_id.in_(nm_ids))
            )
        ).all()
        prod_map = {int(p.nm_id): p for p in prows}
    group_map: dict[int, str] = {}
    if nm_ids:
        grows = (
            await session.execute(
                select(ProductGroupAssignment.nm_id, ProductGroup.name)
                .join(ProductGroup, ProductGroup.id == ProductGroupAssignment.group_id)
                .where(ProductGroupAssignment.nm_id.in_(nm_ids))
            )
        ).all()
        for nm, gname in grows:
            group_map.setdefault(int(nm), gname)
    tenant_names = {
        int(tid): name
        for tid, name in (await session.execute(select(Tenant.id, Tenant.name))).all()
    }

    # Штрафы / приёмка / доплаты / промо / компенсации per nm — DEV-094.
    is_promo = func.coalesce(WbReportDetail.bonus_type_name, "").ilike(_PROMO_BONUS_LIKE)
    extra_map: dict[int, Any] = {}
    if nm_ids:
        erows = (
            await session.execute(
                select(
                    WbReportDetail.nm_id,
                    func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                    func.coalesce(func.sum(WbReportDetail.paid_acceptance), 0).label("acceptance"),
                    func.coalesce(func.sum(case((~is_promo, WbReportDetail.deduction), else_=0)), 0).label("deduction"),
                    func.coalesce(func.sum(case((is_promo, WbReportDetail.deduction), else_=0)), 0).label("promo_ad"),
                    func.coalesce(
                        func.sum(
                            case(
                                (WbReportDetail.supplier_oper_name.notin_(_CORE_OPS), WbReportDetail.ppvz_for_pay),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("comp_ppvz"),
                    func.coalesce(
                        func.sum(
                            case(
                                (WbReportDetail.supplier_oper_name.notin_(_CORE_OPS), WbReportDetail.additional_payment),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("additional"),
                )
                .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date,
                       WbReportDetail.nm_id.isnot(None), *nm_pred)
                .group_by(WbReportDetail.nm_id)
            )
        ).all()
        extra_map = {int(e.nm_id): e for e in erows}

    # Номинальная комиссия WB (тариф по предмету, SCD2 as-of конца периода).
    # Честная ставка = paid_storage_kgvp (FBO, DEV-090: 34.5%, НЕ commission_fbo
    # 38%) минус возврат за опции (unit_plan_global_config.commission_discount_pct,
    # DEV-089, у пользователя 0.75%) → 33.75% — сверено с TS 22-28.06 в процент.
    from app.db.models import UnitPlanGlobalConfig  # noqa: WPS433

    discount = _f(
        (
            await session.execute(
                select(UnitPlanGlobalConfig.commission_discount_pct)
                .order_by(UnitPlanGlobalConfig.id.desc())
                .limit(1)
            )
        ).scalar()
    )
    nominal_rate_by_subject: dict[str, float] = {}
    trows = (
        await session.execute(
            select(
                WbTariffCommission.subject_name,
                WbTariffCommission.paid_storage_kgvp,
                WbTariffCommission.commission_fbo,
                WbTariffCommission.effective_from,
            )
            .where(WbTariffCommission.effective_from <= end_date)
            .order_by(WbTariffCommission.subject_name, WbTariffCommission.effective_from.desc())
        )
    ).all()
    for t in trows:
        key = (t.subject_name or "").strip().lower()
        base_rate = t.paid_storage_kgvp if t.paid_storage_kgvp is not None else t.commission_fbo
        if key and key not in nominal_rate_by_subject and base_rate is not None:
            nominal_rate_by_subject[key] = max(float(base_rate) - discount, 0.0)

    # Ставка налога (АУСН/УСН доход) — pitfall #16: явный tenant-фильтр.
    tid = get_tenant(session)
    tr_stmt = select(AppSetting.value).where(AppSetting.key == "tax_rate")
    if tid is not None:
        tr_stmt = tr_stmt.where(AppSetting.tenant_id == tid)
    tax_rate = float((await session.execute(tr_stmt)).scalar() or 0)

    # Компанейский операционный OPEX за период → аллокация пропорц. реализации.
    opex_total = _f(
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
    )
    total_realisation = sum(_f(r.realisation) for r in rows) or 1.0

    # Тоталы «прочих» (deduction/приёмка/штрафы/промо/компенсации) — как раньше.
    ded_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((~is_promo, WbReportDetail.deduction), else_=0)), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.paid_acceptance), 0).label("acceptance"),
                func.coalesce(func.sum(WbReportDetail.additional_payment), 0).label("additional"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(case((is_promo, WbReportDetail.deduction), else_=0)), 0).label("promo_ad"),
                func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0).label("comp_ppvz"),
            ).where(
                func.date(dcol) >= start_date,
                func.date(dcol) <= end_date,
                WbReportDetail.supplier_oper_name.notin_(_CORE_OPS),
                *nm_pred,
            )
        )
    ).one()
    prochie_total = _f(ded_row.deduction) + _f(ded_row.acceptance)
    acceptance_total = _f(ded_row.acceptance)
    fines_total = _f(ded_row.penalty)
    promo_ad_total = _f(ded_row.promo_ad)
    compensation_total = _f(ded_row.comp_ppvz) + _f(ded_row.additional)

    # Итоговое вознаграждение ВБ (DEV-061, база УПД) — от реального ppvz_vw.
    vw_row = (
        await session.execute(
            select(net(WbReportDetail.ppvz_vw).label("vw"))
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date, *nm_pred)
        )
    ).one()
    vw_reward = _f(vw_row.vw)

    # Детализации (логистика/штрафы/компенсации) для выпадашек плиток (DEV-060).
    log_rows = (
        await session.execute(
            select(
                func.coalesce(WbReportDetail.bonus_type_name, "—").label("cat"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("amt"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date,
                   WbReportDetail.supplier_oper_name == "Логистика", *nm_pred)
            .group_by(WbReportDetail.bonus_type_name)
        )
    ).all()
    logistics_breakdown = sorted(
        ({"category": r.cat, "amount": round(_f(r.amt), 2)} for r in log_rows if abs(_f(r.amt)) >= 0.005),
        key=lambda x: abs(x["amount"]), reverse=True,
    )
    fine_rows = (
        await session.execute(
            select(
                func.coalesce(WbReportDetail.bonus_type_name, "—").label("cat"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("amt"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date,
                   WbReportDetail.penalty != 0, *nm_pred)
            .group_by(WbReportDetail.bonus_type_name)
        )
    ).all()
    fines_breakdown = sorted(
        ({"category": r.cat, "amount": round(_f(r.amt), 2)} for r in fine_rows if abs(_f(r.amt)) >= 0.005),
        key=lambda x: abs(x["amount"]), reverse=True,
    )
    comp_rows = (
        await session.execute(
            select(
                func.coalesce(WbReportDetail.supplier_oper_name, "—").label("cat"),
                func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0).label("amt"),
            )
            .where(func.date(dcol) >= start_date, func.date(dcol) <= end_date,
                   WbReportDetail.supplier_oper_name.notin_(_CORE_OPS),
                   WbReportDetail.ppvz_for_pay != 0, *nm_pred)
            .group_by(WbReportDetail.supplier_oper_name)
        )
    ).all()
    compensation_breakdown = sorted(
        ({"category": r.cat, "amount": round(_f(r.amt), 2)} for r in comp_rows if abs(_f(r.amt)) >= 0.005),
        key=lambda x: abs(x["amount"]), reverse=True,
    )

    returns_rub = _f(
        (
            await session.execute(
                select(func.coalesce(func.sum(WbReportDetail.retail_price), 0)).where(
                    func.date(dcol) >= start_date, func.date(dcol) <= end_date,
                    WbReportDetail.supplier_oper_name == "Возврат", *nm_pred,
                )
            )
        ).scalar()
    )

    # Остатки/капитализация per nm (последний снапшот) — DEV-060 + DEV-094 per-SKU.
    last_snap = (
        await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
    ).scalar()
    stock_map: dict[int, Any] = {}
    price_map: dict[int, float] = {}
    cogs_now: dict[int, float] = {}
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
        stock_map = {int(s.nm_id): s for s in srows if s.nm_id}
        snap_nm = list(stock_map.keys())
        if snap_nm:
            prows2 = (
                await session.execute(
                    select(WbCardPrice.nm_id, WbCardPrice.buyer_price).where(
                        WbCardPrice.nm_id.in_(snap_nm), WbCardPrice.buyer_price.isnot(None)
                    )
                )
            ).all()
            price_map = {int(n): _f(p) for n, p in prows2}
            ccur = (
                await session.execute(
                    select(Cogs.nm_id, Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
                    .where(Cogs.nm_id.in_(snap_nm), Cogs.valid_from <= end_date)
                    .order_by(Cogs.nm_id, Cogs.valid_from.desc())
                )
            ).all()
            for c in ccur:
                if int(c.nm_id) not in cogs_now:
                    cogs_now[int(c.nm_id)] = _f(c.cost_rub) + _f(c.packaging_rub) + _f(c.fulfillment_rub)

    stock_wh = stock_to = stock_from = 0
    cap_cost = cap_price = 0.0
    for nm, s in stock_map.items():
        qty = int(s.qty)
        stock_wh += qty
        stock_to += int(s.to_c)
        stock_from += int(s.from_c)
        total_units = qty + int(s.to_c) + int(s.from_c)
        cap_cost += total_units * cogs_now.get(nm, 0.0)
        cap_price += total_units * price_map.get(nm, 0.0)
    stock_total = stock_wh + stock_to + stock_from
    period_days = (end_date - start_date).days + 1

    # ── items per-SKU ─────────────────────────────────────────────────────
    items: list[dict[str, Any]] = []
    for r in rows:
        nm = int(r.nm_id)
        sales = _f(r.sales)
        realisation = _f(r.realisation)
        net_sold = int(r.sold) - int(r.ret)
        cogs = cogs_map.get(nm, 0.0) * net_sold
        ad = ad_map.get(nm, 0.0)
        tax = sales * tax_rate / 100.0
        share = realisation / total_realisation
        opex = opex_total * share
        prochie = prochie_total * share
        compensation = compensation_total * share
        profit = _f(r.to_transfer) - _f(r.logistics) - _f(r.storage) - cogs - tax - ad - opex - prochie + compensation
        p = prod_map.get(nm)
        e = extra_map.get(nm)
        ocnt, oamt = orders_map.get(nm, (0, 0.0))
        st = stock_map.get(nm)
        st_qty = int(st.qty) if st else 0
        st_to = int(st.to_c) if st else 0
        st_from = int(st.from_c) if st else 0
        st_total = st_qty + st_to + st_from
        nm_cap_cost = st_total * cogs_now.get(nm, 0.0)
        nm_cap_price = st_total * price_map.get(nm, 0.0)
        subj_key = ((p.subject or "") if p else "").strip().lower()
        nominal_rate = nominal_rate_by_subject.get(subj_key)
        profit_wo_opex = profit + opex
        items.append({
            "nm_id": nm,
            "imt_id": int(p.imt_id) if (p and p.imt_id) else None,
            "vendor_code": p.vendor_code if p else None,
            "brand": p.brand if p else None,
            "subject": p.subject if p else None,
            "category": p.category if p else None,
            "group_name": group_map.get(nm),
            "store": tenant_names.get(int(p.tenant_id)) if p else None,
            "photo_url": p.photo_url if p else None,
            "realisation": round(realisation, 2),
            "sales": round(sales, 2),
            "to_transfer": round(_f(r.to_transfer), 2),
            "commission": round(sales - _f(r.to_transfer) - _f(r.acquiring), 2),
            "nominal_commission_pct": nominal_rate,
            "nominal_commission": round(realisation * nominal_rate / 100.0, 2) if nominal_rate else None,
            "acquiring": round(_f(r.acquiring), 2),
            "wb_reward": round(_f(r.vw), 2),
            "logistics": round(_f(r.logistics), 2),
            "storage": round(_f(r.storage), 2),
            "cogs": round(cogs, 2),
            "cogs_unit": round(cogs_map.get(nm, 0.0), 2),
            "ad": round(ad, 2),
            "promo_ad": round(_f(e.promo_ad), 2) if e else 0.0,
            "total_ad": round(ad + (_f(e.promo_ad) if e else 0.0), 2),
            "tax": round(tax, 2),
            "opex": round(opex, 2),
            "deductions": round(prochie, 2),
            "fines": round(_f(e.penalty), 2) if e else 0.0,
            "acceptance": round(_f(e.acceptance), 2) if e else 0.0,
            "compensation": round((_f(e.comp_ppvz) + _f(e.additional)), 2) if e else 0.0,
            "sold": net_sold,
            "returned": int(r.ret),
            "orders_count": ocnt,
            "orders_sum": round(oamt, 2),
            # % выкупа — терминальный из Воронки (buyouts/(buyouts+cancels),
            # как TS); fallback — продажи/заказы при отсутствии funnel.
            "buyout_pct": round(
                buyout_map.get(nm) if buyout_map.get(nm) is not None
                else (sales / oamt * 100 if oamt else 0.0),
                2,
            ),
            "avg_price_before_spp": round(realisation / net_sold, 2) if net_sold else 0.0,
            "avg_price_sale": round(sales / net_sold, 2) if net_sold else 0.0,
            "avg_logistics_per_unit": round(_f(r.logistics) / net_sold, 2) if net_sold else 0.0,
            "avg_profit_per_unit": round(profit / net_sold, 2) if net_sold else 0.0,
            "profit": round(profit, 2),
            "profit_wo_opex": round(profit_wo_opex, 2),
            "margin_pct": round(profit / sales * 100, 2) if sales > 0 else 0.0,
            "margin_wo_opex_pct": round(profit_wo_opex / sales * 100, 2) if sales > 0 else 0.0,
            "roi_pct": round(profit / cogs * 100, 2) if cogs > 0 else 0.0,
            "revenue_share_pct": round(share * 100, 2),
            "drr_sales_pct": round(ad / realisation * 100, 2) if realisation > 0 else 0.0,
            "drrz_pct": round(ad / oamt * 100, 2) if oamt else 0.0,
            "total_drr_pct": round((ad + (_f(e.promo_ad) if e else 0.0)) / realisation * 100, 2) if realisation > 0 else 0.0,
            "stock_wh": st_qty,
            "stock_to_client": st_to,
            "stock_from_client": st_from,
            "stock_total": st_total,
            "cap_by_cost": round(nm_cap_cost, 2),
            "cap_by_price": round(nm_cap_price, 2),
            "turnover_sales_days": round(st_total / (net_sold / period_days), 2) if net_sold > 0 else None,
            "turnover_orders_days": round(st_total / (ocnt / period_days), 2) if ocnt else None,
            "gmroi_pct": round(profit / nm_cap_cost * 100, 2) if nm_cap_cost > 0 else None,
            "gmroi_annual_pct": round(profit / nm_cap_cost * 100 * 365 / period_days, 2) if nm_cap_cost > 0 else None,
        })
    items.sort(key=lambda x: x["realisation"], reverse=True)

    # ABC по прибыли и по выручке (кумулятивно: A ≤80%, B ≤95%, C остальное).
    def _abc(field: str, out_key: str) -> None:
        total = sum(max(x[field], 0.0) for x in items) or 1.0
        cum = 0.0
        for x in sorted(items, key=lambda i: i[field], reverse=True):
            cum += max(x[field], 0.0)
            x[out_key] = "A" if cum <= total * 0.8 else ("B" if cum <= total * 0.95 else "C")

    _abc("profit", "abc_profit")
    _abc("realisation", "abc_revenue")

    # Группировка по склейке (imt) — DEV-094: суммируем аддитивные поля.
    if group_by == "imt":
        items = _group_by_imt(items, period_days)

    # ── totals ────────────────────────────────────────────────────────────
    def _s(f: str) -> float:
        return round(sum(x[f] for x in items), 2)

    realisation_t, sales_t, cogs_t = _s("realisation"), _s("sales"), _s("cogs")
    logistics_t, storage_t = _s("logistics"), _s("storage")
    commission_t, acquiring_t = _s("commission"), _s("acquiring")
    profit_t, opex_t = _s("profit"), _s("opex")
    ad_t = _s("ad")
    sold_t = sum(x["sold"] for x in items)
    orders_cnt_t = sum(x["orders_count"] for x in items)
    orders_sum_t = _s("orders_sum")
    nominal_t = round(sum((x["nominal_commission"] or 0.0) for x in items), 2)
    profit_wo_opex_t = round(profit_t + opex_t, 2)
    R = realisation_t or 1.0

    def _pct(v: float) -> float:
        return round(v / R * 100, 2)

    # GMROI: определение = прибыль периода / капитализация по себес × 100.
    # Годовой = аннуализация (×365/период). NB: снапшоты остатков копятся с
    # 05.2026 — это не скользящая годовая средняя, а текущий срез.
    gmroi = round(profit_t / cap_cost * 100, 2) if cap_cost > 0 else None
    gmroi_annual = round(profit_t / cap_cost * 100 * 365 / period_days, 2) if cap_cost > 0 else None

    # Свои склады (off-platform) — реальные цифры из журнала движений.
    from app.services.off_platform import summary as off_summary  # noqa: WPS433

    own = await off_summary(session)
    own_units = int(own.get("total_qty") or 0)
    own_cap = _f(own.get("total_capitalization"))

    tot = {
        "realisation": realisation_t,
        "sales": sales_t,
        "to_transfer": _s("to_transfer"),
        "cogs": cogs_t,
        "cogs_pct": _pct(cogs_t),
        "ad": ad_t,
        "tax": _s("tax"),
        "tax_pct": _pct(_s("tax")),
        "tax_base": sales_t,
        "opex": opex_t,
        "opex_pct": _pct(opex_t),
        "profit": profit_t,
        "profit_wo_opex": profit_wo_opex_t,
        "margin_pct": round(profit_t / R * 100, 2),
        "margin_wo_opex_pct": round(profit_wo_opex_t / R * 100, 2),
        "sold": sold_t,
        "returned": sum(x["returned"] for x in items),
        "returns_rub": round(returns_rub, 2),
        "logistics": logistics_t,
        "logistics_pct": _pct(logistics_t),
        "storage": storage_t,
        "storage_pct": _pct(storage_t),
        "commission": round(commission_t + acquiring_t, 2),
        "commission_pct": _pct(commission_t + acquiring_t),
        "acquiring": acquiring_t,
        # Номинальная комиссия WB (тариф kgvpMarketplace по предмету) — DEV-094.
        "nominal_commission": nominal_t,
        "nominal_commission_pct": _pct(nominal_t),
        "roi_pct": round(profit_t / cogs_t * 100, 2) if cogs_t else 0.0,
        "deductions": round(prochie_total, 2),
        "deductions_pct": _pct(prochie_total),
        "fines": round(fines_total, 2),
        "acceptance": round(acceptance_total, 2),
        "acceptance_pct": _pct(acceptance_total),
        "compensation": round(compensation_total, 2),
        "compensation_pct": _pct(compensation_total),
        "promo_ad": round(promo_ad_total, 2),
        # ДРР бонусов (WB Продвижение из финотчёта) + общая ДРР — DEV-094.
        "drr_bonus_pct": _pct(promo_ad_total),
        "total_ad": round(ad_t + promo_ad_total, 2),
        "total_drr_pct": _pct(ad_t + promo_ad_total),
        "orders_count": orders_cnt_t or None,
        "orders_sum": round(orders_sum_t, 2),
        # Терминальный % выкупа из Воронки (как TS); fallback продажи/заказы.
        "buyout_pct": round(
            buyout_b_total / (buyout_b_total + buyout_c_total) * 100, 2
        ) if (buyout_b_total + buyout_c_total) > 0
        else (round(sales_t / orders_sum_t * 100, 2) if orders_sum_t else 0.0),
        "drr_pct": _pct(ad_t),
        "drrz_pct": round(ad_t / orders_sum_t * 100, 2) if orders_sum_t else 0.0,
        "avg_price_sale": round(sales_t / sold_t, 2) if sold_t else 0.0,
        "avg_price_before_spp": round(realisation_t / sold_t, 2) if sold_t else 0.0,
        "avg_logistics_per_unit": round(logistics_t / sold_t, 2) if sold_t else 0.0,
        "avg_profit_per_unit": round(profit_t / sold_t, 2) if sold_t else 0.0,
        "stock_total": stock_total,
        "stock_wh": stock_wh,
        "stock_to_client": stock_to,
        "stock_from_client": stock_from,
        "cap_by_cost": round(cap_cost, 2),
        "cap_by_price": round(cap_price, 2),
        "turnover_sales_days": round(stock_total / (sold_t / period_days), 2) if sold_t else None,
        "turnover_orders_days": round(stock_total / (orders_cnt_t / period_days), 2) if orders_cnt_t else None,
        "gmroi": gmroi,
        "gmroi_annual": gmroi_annual,
        "wb_final_reward": round(
            vw_reward + logistics_t + storage_t
            + acceptance_total + fines_total + prochie_total - compensation_total,
            2,
        ),
        "own_stock_units": own_units,
        "own_stock_cap": round(own_cap, 2),
    }

    out = {
        "reporting_mode": reporting_mode,
        "tax_rate": tax_rate,
        "group_by": group_by,
        "items": items,
        "totals": tot,
        "logistics_breakdown": [{**b, "pct": _pct(b["amount"])} for b in logistics_breakdown],
        "fines_breakdown": [{**b, "pct": _pct(b["amount"])} for b in fines_breakdown],
        "compensation_breakdown": [{**b, "pct": _pct(b["amount"])} for b in compensation_breakdown],
        "published_through": published_max.isoformat() if published_max else None,
        "estimated_from": estimated_from.isoformat() if estimated_from else None,
    }

    # Дельты к предыдущему равному периоду (DEV-094, «динамика» как у TS).
    if include_prev:
        n_days = (end_date - start_date).days
        prev_to = start_date - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n_days)
        prev = await build_summary_report(
            session, start_date=prev_from, end_date=prev_to,
            reporting_mode=reporting_mode, nm_scope=nm_scope,
            group_by=group_by, include_prev=False,
        )
        prev_by_key = {x.get("nm_id") or x.get("imt_id"): x for x in prev["items"]}
        _DELTA_FIELDS = ("realisation", "sales", "profit", "orders_count", "orders_sum",
                         "avg_price_sale", "avg_price_before_spp", "ad")
        for x in items:
            px = prev_by_key.get(x.get("nm_id") or x.get("imt_id"))
            x["prev"] = {f: (px[f] if px else 0) for f in _DELTA_FIELDS}
        out["prev_totals"] = prev["totals"]
        out["prev_period"] = {"from": prev_from.isoformat(), "to": prev_to.isoformat()}

    return out


_IMT_SUM_FIELDS = (
    "realisation", "sales", "to_transfer", "commission", "acquiring", "wb_reward",
    "logistics", "storage", "cogs", "ad", "promo_ad", "total_ad", "tax", "opex",
    "deductions", "fines", "acceptance", "compensation", "sold", "returned",
    "orders_count", "orders_sum", "profit", "profit_wo_opex",
    "stock_wh", "stock_to_client", "stock_from_client", "stock_total",
    "cap_by_cost", "cap_by_price",
)


def _group_by_imt(items: list[dict[str, Any]], period_days: int) -> list[dict[str, Any]]:
    """Схлопнуть per-SKU строки в склейки (imt_id). SKU без склейки — как есть."""
    merged: dict[Any, dict[str, Any]] = {}
    singles: list[dict[str, Any]] = []
    counts: dict[Any, int] = {}
    for x in items:
        imt = x.get("imt_id")
        if not imt:
            singles.append(x)
            continue
        counts[imt] = counts.get(imt, 0) + 1
        g = merged.get(imt)
        if g is None:
            g = dict(x)
            merged[imt] = g
            continue
        for f in _IMT_SUM_FIELDS:
            g[f] = round((g.get(f) or 0) + (x.get(f) or 0), 2)
    out = []
    for imt, g in merged.items():
        if counts[imt] > 1:
            g["vendor_code"] = f"{g.get('vendor_code') or imt} (склейка ×{counts[imt]})"
            g["nominal_commission"] = None
            g["nominal_commission_pct"] = None
        # пересчёт производных
        sales, realisation = g["sales"], g["realisation"]
        sold, oamt, ocnt = g["sold"], g["orders_sum"], g["orders_count"]
        profit, cogs = g["profit"], g["cogs"]
        g["buyout_pct"] = round(sales / oamt * 100, 2) if oamt else 0.0
        g["avg_price_before_spp"] = round(realisation / sold, 2) if sold else 0.0
        g["avg_price_sale"] = round(sales / sold, 2) if sold else 0.0
        g["avg_logistics_per_unit"] = round(g["logistics"] / sold, 2) if sold else 0.0
        g["avg_profit_per_unit"] = round(profit / sold, 2) if sold else 0.0
        g["margin_pct"] = round(profit / sales * 100, 2) if sales > 0 else 0.0
        g["margin_wo_opex_pct"] = round(g["profit_wo_opex"] / sales * 100, 2) if sales > 0 else 0.0
        g["roi_pct"] = round(profit / cogs * 100, 2) if cogs > 0 else 0.0
        g["drr_sales_pct"] = round(g["ad"] / realisation * 100, 2) if realisation > 0 else 0.0
        g["drrz_pct"] = round(g["ad"] / oamt * 100, 2) if oamt else 0.0
        g["total_drr_pct"] = round(g["total_ad"] / realisation * 100, 2) if realisation > 0 else 0.0
        g["turnover_sales_days"] = round(g["stock_total"] / (sold / period_days), 2) if sold > 0 else None
        g["turnover_orders_days"] = round(g["stock_total"] / (ocnt / period_days), 2) if ocnt else None
        g["gmroi_pct"] = round(profit / g["cap_by_cost"] * 100, 2) if g["cap_by_cost"] > 0 else None
        g["gmroi_annual_pct"] = (
            round(profit / g["cap_by_cost"] * 100 * 365 / period_days, 2) if g["cap_by_cost"] > 0 else None
        )
        out.append(g)
    out.extend(singles)
    # revenue_share пересчитывается от нового набора строк.
    total_r = sum(x["realisation"] for x in out) or 1.0
    for x in out:
        x["revenue_share_pct"] = round(x["realisation"] / total_r * 100, 2)
    out.sort(key=lambda x: x["realisation"], reverse=True)
    return out
