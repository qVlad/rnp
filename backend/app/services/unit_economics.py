"""Per-SKU unit economics: revenue, commission, ad spend, COGS, margin, days-to-stockout."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Cogs,
    ExternalAdCost,
    Product,
    WbAdStatsDaily,
    WbOrder,
    WbPaidStorage,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.pnl_builder import DEFAULT_MIN_TAX_RATE, DEFAULT_TAX_RATE, _compute_tax
from app.services.settings_timeline import (
    load_static_settings,
    load_timeline,
    parse_value,
    value_for_date,
)


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def _latest_cogs(session: AsyncSession) -> dict[int, dict[str, float]]:
    rows = (
        await session.execute(
            select(
                Cogs.nm_id,
                Cogs.cost_rub,
                Cogs.packaging_rub,
                Cogs.fulfillment_rub,
                Cogs.valid_from,
            ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
        )
    ).all()
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        nm = int(r.nm_id)
        if nm in out:
            continue
        out[nm] = {
            "cost": _f(r.cost_rub),
            "pack": _f(r.packaging_rub),
            "ful": _f(r.fulfillment_rub),
        }
    return out


async def build_unit_economics(
    session: AsyncSession,
    *,
    days_back: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    include_archived: bool = False,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Per-SKU unit economics with full P&L breakdown.

    Args:
        days_back: rolling window (used if start_date/end_date are not provided).
        start_date / end_date: explicit calendar range (inclusive). If both
            provided, override days_back.
    """
    if start_date is not None and end_date is not None:
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        days_back = max(1, (end_date - start_date).days + 1)
    else:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    sales_stmt = (
        select(
            WbSale.nm_id,
            func.count().label("rows"),
            func.sum(case((WbSale.is_return, 0), else_=1)).label("gross_units"),
            func.sum(case((WbSale.is_return, 1), else_=0)).label("returns"),
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
            func.sum(case((WbSale.is_return, 0), else_=WbSale.for_pay)).label("for_pay"),
            func.sum(case((WbSale.is_return, 0), else_=WbSale.price_with_disc)).label(
                "price_with_disc"
            ),
            func.avg(WbSale.commission_percent).label("commission_pct"),
        )
        .where(WbSale.sale_dt >= start, WbSale.sale_dt < end)
        .group_by(WbSale.nm_id)
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_rows = (await session.execute(sales_stmt)).all()

    # Aggregate full P&L picture per nm from wb_report_detail — same logic
    # as build_pnl: ppvz/acquiring on (Продажа − Возврат), delivery/storage/
    # penalty summed across all rows. Plus extra categories that the user
    # spreadsheet uses as separate columns (платная приёмка / списание баллов /
    # коррекция эквайринга).
    # Каноничные предикаты в services/period_aggregates.py.
    from app.services.period_aggregates import (
        OP_SALE as rd_is_sale,
        OP_RETURN as rd_is_return,
        REVENUE_FIELD as rd_revenue_field,
    )
    rd_is_acceptance = WbReportDetail.supplier_oper_name.in_(
        [
            "Возмещение за выдачу и возврат товаров на ПВЗ",
            "Платная приемка",
            "Платная приёмка",
        ]
    )
    rd_is_loyalty = WbReportDetail.supplier_oper_name.in_(
        [
            "Компенсация скидки по программе лояльности",
            "Списание за баллы",
        ]
    )
    rd_is_acquiring_correction = (
        WbReportDetail.supplier_oper_name == "Корректировка эквайринга"
    )
    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            func.coalesce(
                func.sum(case((rd_is_sale, rd_revenue_field), else_=0)), 0
            ).label("rev_sale"),
            func.coalesce(
                func.sum(case((rd_is_return, rd_revenue_field), else_=0)), 0
            ).label("rev_return"),
            func.coalesce(
                func.sum(case((rd_is_sale, WbReportDetail.ppvz_for_pay), else_=0)), 0
            ).label("ppvz_sale"),
            func.coalesce(
                func.sum(case((rd_is_return, WbReportDetail.ppvz_for_pay), else_=0)), 0
            ).label("ppvz_return"),
            # retail_amount = «Стоимость продажи» которую WB пропечатывает
            # в УПД для ФНС. Юридически корректная база для АУСН/УСН-доход
            # (см. письмо Минфина / WB Финотчёт). Сходится с Excel налогом 1:1.
            func.coalesce(
                func.sum(case((rd_is_sale, WbReportDetail.retail_amount), else_=0)), 0
            ).label("retail_amt_sale"),
            func.coalesce(
                func.sum(case((rd_is_return, WbReportDetail.retail_amount), else_=0)), 0
            ).label("retail_amt_return"),
            func.coalesce(
                func.sum(case((rd_is_sale, WbReportDetail.acquiring_fee), else_=0)), 0
            ).label("acq_sale"),
            func.coalesce(
                func.sum(case((rd_is_return, WbReportDetail.acquiring_fee), else_=0)), 0
            ).label("acq_return"),
            func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("delivery"),
            func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
            func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
            func.coalesce(
                func.sum(case((rd_is_acceptance, WbReportDetail.delivery_rub), else_=0))
                + func.sum(case((rd_is_acceptance, WbReportDetail.deduction), else_=0)),
                0,
            ).label("acceptance_fee"),
            func.coalesce(
                func.sum(case((rd_is_loyalty, WbReportDetail.deduction), else_=0)),
                0,
            ).label("loyalty_writeoff"),
            func.coalesce(
                func.sum(case((rd_is_acquiring_correction, WbReportDetail.acquiring_fee), else_=0)),
                0,
            ).label("acquiring_correction"),
            func.coalesce(
                func.sum(case((rd_is_sale, 1), else_=0))
                - func.sum(case((rd_is_return, 1), else_=0)),
                0,
            ).label("rd_units_net"),
            func.coalesce(
                func.sum(case((rd_is_sale, 1), else_=0)), 0
            ).label("rd_units_sale"),
            func.coalesce(
                func.sum(case((rd_is_return, 1), else_=0)), 0
            ).label("rd_units_return"),
        )
        .where(
            # sale_dt — каноничное поле даты для report_detail (совпадает с
            # WB-кабинетом). См. period_aggregates.sale_dt_filter / CLAUDE.md.
            WbReportDetail.sale_dt >= start,
            WbReportDetail.sale_dt < end,
            WbReportDetail.nm_id.isnot(None),
        )
        .group_by(WbReportDetail.nm_id)
    )
    if nm_filter is not None:
        rd_stmt = rd_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    rd_rows = (await session.execute(rd_stmt)).all()

    # Aggregate-only (nm_id IS NULL) buckets that WB не привязывает к SKU:
    # Хранение, Платная приёмка (через ppvz_vw), Удержания, Лояльность.
    # Распределим их пропорционально remaining stock / fact продаж per nm
    # ниже в основном цикле.
    rd_unallocated_stmt = select(
        func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage_unalloc"),
        func.coalesce(
            func.sum(
                case(
                    (
                        WbReportDetail.supplier_oper_name == "Возмещение за выдачу и возврат товаров на ПВЗ",
                        # ppvz_vw + ppvz_vw_nds приходят отрицательными для удержания —
                        # переводим в положительное «расход для нас».
                        -(func.coalesce(WbReportDetail.ppvz_vw, 0)
                          + func.coalesce(WbReportDetail.ppvz_vw_nds, 0)),
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("acceptance_unalloc"),
        func.coalesce(
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == "Удержание", WbReportDetail.deduction),
                    else_=0,
                )
            ),
            0,
        ).label("deduction_unalloc"),
        func.coalesce(
            func.sum(
                case(
                    (
                        WbReportDetail.supplier_oper_name.in_(
                            [
                                "Компенсация скидки по программе лояльности",
                                "Коррекция компенсации скидки по программе лояльности",
                            ]
                        ),
                        WbReportDetail.deduction,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("loyalty_unalloc"),
    ).where(
        WbReportDetail.sale_dt >= start,
        WbReportDetail.sale_dt < end,
        WbReportDetail.nm_id.is_(None),
    )
    # Brand filter не применяется к unallocated buckets — WB их шлёт без nm и
    # без brand. Распределение идёт по тому же brand-set что и products.
    unalloc_row = (await session.execute(rd_unallocated_stmt)).one()
    storage_unalloc = _f(unalloc_row.storage_unalloc)
    acceptance_unalloc = _f(unalloc_row.acceptance_unalloc)
    deduction_unalloc = _f(unalloc_row.deduction_unalloc)
    loyalty_unalloc = _f(unalloc_row.loyalty_unalloc)

    commission_by_nm: dict[int, float] = {}
    rd_metrics_by_nm: dict[int, dict[str, float]] = {}
    for r in rd_rows:
        rev_sale = _f(r.rev_sale)
        rev_return = _f(r.rev_return)
        ppvz_sale = _f(r.ppvz_sale)
        ppvz_return = _f(r.ppvz_return)
        acq_sale = _f(r.acq_sale)
        acq_return = _f(r.acq_return)
        ppvz_net = ppvz_sale - ppvz_return
        acq_net = acq_sale - acq_return
        retail_amt_net = _f(r.retail_amt_sale) - _f(r.retail_amt_return)
        delivery = _f(r.delivery)
        storage = _f(r.storage)
        penalty = _f(r.penalty)
        acceptance_fee = _f(r.acceptance_fee)
        loyalty_writeoff = _f(r.loyalty_writeoff)
        acquiring_correction = _f(r.acquiring_correction)
        # Net WB-комиссия = (ppvz_net вычтенный из revenue_net), показываем
        # отдельной колонкой как в WB-кабинете.
        revenue_net = rev_sale - rev_return
        commission_wb = revenue_net - ppvz_net
        if rev_sale > 0:
            commission_by_nm[int(r.nm_id)] = (rev_sale - ppvz_sale) / rev_sale * 100
        rd_metrics_by_nm[int(r.nm_id)] = {
            "rev_sale": rev_sale,
            "rev_return": rev_return,
            "revenue_net": revenue_net,
            "ppvz_sale": ppvz_sale,
            "ppvz_return": ppvz_return,
            "ppvz_net": ppvz_net,
            "acquiring_net": acq_net,
            "commission_wb": commission_wb,
            "delivery": delivery,
            "storage": storage,
            "penalty": penalty,
            "acceptance_fee": acceptance_fee,
            "loyalty_writeoff": loyalty_writeoff,
            "acquiring_correction": acquiring_correction,
            "retail_amt_net": retail_amt_net,
            "rd_units_net": int(r.rd_units_net or 0),
            "rd_units_sale": int(r.rd_units_sale or 0),
            "rd_units_return": int(r.rd_units_return or 0),
            # Final payout to bank account per nm (matches WB cabinet payout).
            "payout": (
                ppvz_net - acq_net - delivery - storage - penalty
                - acceptance_fee - loyalty_writeoff - acquiring_correction
            ),
        }

    # Active orders (is_cancel=False) — это "Заказы" в UI и знаменатель ДРР.
    # Total orders (active + cancellations) — знаменатель «выкупа», как в WB-кабинете
    # и на дашборде (см. metrics._compute_window_kpis): отменённые покупателем
    # тоже учитываются в total_orders.
    orders_stmt = (
        select(
            WbOrder.nm_id,
            func.coalesce(func.sum(case((WbOrder.is_cancel, 0), else_=1)), 0).label("active"),
            func.coalesce(func.sum(case((WbOrder.is_cancel, 1), else_=0)), 0).label("cancelled"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            WbOrder.is_cancel,
                            0,
                        ),
                        else_=WbOrder.total_price * (1 - WbOrder.discount_percent / 100),
                    )
                ),
                0,
            ).label("revenue"),
        )
        .where(WbOrder.order_dt >= start, WbOrder.order_dt < end)
        .group_by(WbOrder.nm_id)
    )
    if nm_filter is not None:
        orders_stmt = orders_stmt.where(WbOrder.nm_id.in_(nm_filter))
    orders_rows = (await session.execute(orders_stmt)).all()
    orders_by_nm = {
        int(r.nm_id): {
            "orders": int(r.active),
            "total_orders": int(r.active) + int(r.cancelled),
            "revenue": _f(r.revenue),
        }
        for r in orders_rows
    }

    ad_stmt = (
        select(
            WbAdStatsDaily.nm_id,
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
            func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("ad_orders"),
        )
        .where(
            WbAdStatsDaily.stat_date >= start.date(),
            WbAdStatsDaily.stat_date < end.date(),
            WbAdStatsDaily.nm_id.isnot(None),
        )
        .group_by(WbAdStatsDaily.nm_id)
    )
    if nm_filter is not None:
        ad_stmt = ad_stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    ad_rows = (await session.execute(ad_stmt)).all()
    ad_by_nm = {int(r.nm_id): {"ad_cost": _f(r.ad_cost), "ad_orders": int(r.ad_orders)} for r in ad_rows}

    # External (off-WB) marketing costs by SKU.
    ext_stmt = (
        select(
            ExternalAdCost.nm_id,
            func.coalesce(func.sum(ExternalAdCost.amount), 0).label("ext_cost"),
        )
        .where(
            ExternalAdCost.spend_date >= start.date(),
            ExternalAdCost.spend_date < end.date(),
            ExternalAdCost.nm_id.isnot(None),
        )
        .group_by(ExternalAdCost.nm_id)
    )
    if nm_filter is not None:
        ext_stmt = ext_stmt.where(ExternalAdCost.nm_id.in_(nm_filter))
    ext_rows = (await session.execute(ext_stmt)).all()
    ext_ad_by_nm: dict[int, float] = {int(r.nm_id): _f(r.ext_cost) for r in ext_rows}

    # External marketing distribution (см. миграцию 0032). Три уровня:
    #   1. nm_id NOT NULL → прямой расход на SKU (выше — `ext_ad_by_nm`).
    #   2. nm_id IS NULL, brand IS NOT NULL → бренд-level. Распределяется
    #      pro-rata по выручке SKU **этого** бренда (manager видит свои).
    #   3. nm_id IS NULL, brand IS NULL → company-wide. Распределяется
    #      pro-rata по выручке всех видимых SKU. Manager НЕ видит
    #      (только director/head).
    brand_ext_rows_stmt = (
        select(
            ExternalAdCost.brand,
            func.coalesce(func.sum(ExternalAdCost.amount), 0).label("amt"),
        )
        .where(
            ExternalAdCost.spend_date >= start.date(),
            ExternalAdCost.spend_date < end.date(),
            ExternalAdCost.nm_id.is_(None),
            ExternalAdCost.brand.is_not(None),
        )
        .group_by(ExternalAdCost.brand)
    )
    if brands is not None:
        brand_ext_rows_stmt = brand_ext_rows_stmt.where(
            ExternalAdCost.brand.in_(list(brands))
        )
    brand_ext_total_by_brand: dict[str, float] = {
        r.brand: _f(r.amt)
        for r in (await session.execute(brand_ext_rows_stmt)).all()
    }

    # Company-wide расход видят только полные роли. Manager (brands ≠ None) — нет.
    if brands is None:
        company_ext_total = _f(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ExternalAdCost.amount), 0)).where(
                        ExternalAdCost.spend_date >= start.date(),
                        ExternalAdCost.spend_date < end.date(),
                        ExternalAdCost.nm_id.is_(None),
                        ExternalAdCost.brand.is_(None),
                    )
                )
            ).scalar_one()
        )
    else:
        company_ext_total = 0.0

    latest_dt = select(func.max(WbStockSnapshot.snapshot_dt)).scalar_subquery()
    stock_stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
            func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("in_to"),
            func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("in_from"),
        )
        .where(WbStockSnapshot.snapshot_dt == latest_dt)
        .group_by(WbStockSnapshot.nm_id)
    )
    if nm_filter is not None:
        stock_stmt = stock_stmt.where(WbStockSnapshot.nm_id.in_(nm_filter))
    stock_rows = (await session.execute(stock_stmt)).all()
    stock_by_nm = {int(r.nm_id): int(r.qty or 0) for r in stock_rows}
    in_way_by_nm = {
        int(r.nm_id): {"to_client": int(r.in_to or 0), "from_client": int(r.in_from or 0)}
        for r in stock_rows
    }

    # Точное хранение per nm из WB Analytics API (`/api/v1/paid_storage`).
    # Заполняется celery-таской `sync_paid_storage` (раз в день за 7 дней).
    # Если за период есть данные — используем их вместо пропорционального
    # распределения общего storage_fee из report_detail.
    paid_storage_stmt = (
        select(
            WbPaidStorage.nm_id,
            func.coalesce(func.sum(WbPaidStorage.warehouse_price), 0).label("amount"),
        )
        .where(
            WbPaidStorage.date >= start.date(),
            # `end` уже exclusive (datetime midnight следующего дня), поэтому
            # `WbPaidStorage.date < end.date()` исключает день `end.date()`.
            # Без `+ 1 day` — иначе захватим лишний календарный день.
            WbPaidStorage.date < end.date(),
        )
        .group_by(WbPaidStorage.nm_id)
    )
    if nm_filter is not None:
        paid_storage_stmt = paid_storage_stmt.where(WbPaidStorage.nm_id.in_(nm_filter))
    paid_storage_rows = (await session.execute(paid_storage_stmt)).all()
    paid_storage_by_nm: dict[int, float] = {
        int(r.nm_id): _f(r.amount) for r in paid_storage_rows
    }
    has_paid_storage_data = bool(paid_storage_by_nm)

    # Use the historical cost lookup so old sales get the cost that was valid then.
    # Lazy import to avoid circular module imports.
    from app.services.pnl_builder import build_cogs_lookup, cost_for_date  # noqa: WPS433

    cogs_lookup = await build_cogs_lookup(session)
    midpoint = (start + (end - start) / 2).date()  # representative date for the window

    # Tax/VAT settings effective at midpoint of the window.
    timeline = await load_timeline(session)
    static_settings = await load_static_settings(session)
    tax_system = (
        parse_value("tax_system", value_for_date(timeline, static_settings, "tax_system", midpoint))
        or "none"
    )
    tax_rate_v = parse_value(
        "tax_rate", value_for_date(timeline, static_settings, "tax_rate", midpoint)
    )
    tax_rate = (
        float(tax_rate_v) if tax_rate_v is not None else DEFAULT_TAX_RATE.get(tax_system, 0.0)
    )
    tax_min_rate_v = parse_value(
        "tax_min_rate", value_for_date(timeline, static_settings, "tax_min_rate", midpoint)
    )
    tax_min_rate = (
        float(tax_min_rate_v) if tax_min_rate_v is not None else DEFAULT_MIN_TAX_RATE.get(tax_system, 0.0)
    )
    reduce_by_insurance = bool(
        parse_value(
            "reduce_by_insurance",
            value_for_date(timeline, static_settings, "reduce_by_insurance", midpoint),
        )
    )
    vat_payer = bool(
        parse_value("vat_payer", value_for_date(timeline, static_settings, "vat_payer", midpoint))
    )
    vat_rate_v = parse_value(
        "vat_rate", value_for_date(timeline, static_settings, "vat_rate", midpoint)
    )
    vat_rate = float(vat_rate_v) if vat_rate_v is not None else 0.0

    products_stmt = select(Product)
    if brands is not None:
        products_stmt = products_stmt.where(Product.brand.in_(list(brands)))
    all_products = (await session.execute(products_stmt)).scalars().all()
    products = {p.nm_id: p for p in all_products}
    archived_nm_ids: set[int] = (
        set() if include_archived else {p.nm_id for p in all_products if p.is_archived}
    )

    # First pass — gather per-SKU revenue so we can distribute brand-level
    # external ad spend pro-rata by revenue afterwards.
    nm_set = (
        set(orders_by_nm.keys())
        | set(int(r.nm_id) for r in sales_rows)
        | set(stock_by_nm.keys())
    )
    if archived_nm_ids:
        nm_set -= archived_nm_ids
    # Каноничная выручка — из report_detail (rev_sale − rev_return), как
    # на P&L и Dashboard final. Старый источник `wb_orders.total_price` давал
    # на 5-15% выше из-за preliminary-лага и ломал сверку между страницами.
    # Для SKU которых пока нет в report_detail (последние 1-2 дня) делаем
    # fallback на orders-revenue чтобы карточка не светилась нулём.
    revenue_by_nm: dict[int, float] = {}
    for nm in nm_set:
        rd = rd_metrics_by_nm.get(nm)
        if rd is not None:
            revenue_by_nm[nm] = rd["rev_sale"] - rd["rev_return"]
        else:
            revenue_by_nm[nm] = orders_by_nm.get(nm, {}).get("revenue", 0.0)
    total_revenue = sum(revenue_by_nm.values())

    # Aggregate distribution bases (для разнесения unallocated buckets):
    # хранение → пропорционально текущему остатку (товар занимает место);
    # платная приёмка / удержание / лояльность → пропорционально продажам.
    total_stock_for_alloc = sum(stock_by_nm.get(nm, 0) for nm in nm_set)
    units_sold_by_nm: dict[int, int] = {}
    for sr in sales_rows:
        nm_v = int(sr.nm_id)
        if nm_v in nm_set:
            units_sold_by_nm[nm_v] = max(0, int(sr.units or 0))
    total_units_sold_for_alloc = sum(units_sold_by_nm.values())

    # WB Удержания (deduction_unalloc) ⊇ реклама + джем + аренда PVZ + прочее.
    # WB advert API (`/adv/v3/fullstats` → wb_ad_stats_daily) даёт ТОЧНУЮ
    # сумму рекламы per-nm; остаток Удержаний считаем «прочими удержаниями»
    # и распределяем pro-rata по продажам. Если advert API недосинкан
    # (бэкфилл за свежие даты ещё не доехал из-за rate-limit), other будет
    # переоценен — ничего страшного, итоговая сумма (ad+other) всё равно
    # совпадает с Удержания_total.
    total_wb_ad_cost = sum(
        _f(v.get("ad_cost", 0.0)) for v in ad_by_nm.values()
    )
    other_deductions_total = max(0.0, deduction_unalloc - total_wb_ad_cost)

    def share_by_stock(nm: int) -> float:
        if total_stock_for_alloc <= 0:
            return (1.0 / len(nm_set)) if nm_set else 0.0
        return stock_by_nm.get(nm, 0) / total_stock_for_alloc

    def share_by_sold(nm: int) -> float:
        if total_units_sold_for_alloc <= 0:
            return (1.0 / len(nm_set)) if nm_set else 0.0
        return units_sold_by_nm.get(nm, 0) / total_units_sold_for_alloc

    # Подсчёт выручки в разрезе бренда — нужен для pro-rata распределения
    # бренд-level расходов внутри своего бренда.
    revenue_by_brand: dict[str, float] = {}
    nm_to_brand: dict[int, str | None] = {}
    for nm in nm_set:
        prod = products.get(nm)
        b = prod.brand if prod else None
        nm_to_brand[nm] = b
        if b:
            revenue_by_brand[b] = revenue_by_brand.get(b, 0.0) + revenue_by_nm.get(nm, 0.0)

    def brand_share_for(nm: int) -> float:
        share = 0.0
        # 1. Бренд-level: распределяется по выручке SKU внутри своего бренда.
        b = nm_to_brand.get(nm)
        brand_pool = brand_ext_total_by_brand.get(b or "", 0.0) if b else 0.0
        brand_rev = revenue_by_brand.get(b or "", 0.0) if b else 0.0
        if brand_pool > 0 and brand_rev > 0:
            share += brand_pool * (revenue_by_nm.get(nm, 0.0) / brand_rev)
        # 2. Company-wide: pro-rata по всей видимой выручке (для director/head).
        if company_ext_total > 0 and total_revenue > 0:
            share += company_ext_total * (revenue_by_nm.get(nm, 0.0) / total_revenue)
        return share

    items: list[dict[str, Any]] = []
    for nm in nm_set:
        prod = products.get(nm)
        sale = next((r for r in sales_rows if int(r.nm_id) == nm), None)
        units_sold = int(sale.units or 0) if sale else 0
        gross_units = int(sale.gross_units or 0) if sale else 0
        returns_count = int(sale.returns or 0) if sale else 0
        for_pay = _f(sale.for_pay) if sale else 0.0
        avg_price = (
            _f(sale.price_with_disc) / max(1, int(sale.rows or 0)) if sale and sale.rows else 0.0
        )
        # Prefer commission_pct calculated from wb_report_detail (real WB %).
        # Fall back to wb_sales.commission_percent for older periods where
        # report_detail hasn't arrived yet.
        commission_pct = commission_by_nm.get(nm) or (_f(sale.commission_pct) if sale else 0.0)

        orders = orders_by_nm.get(nm, {}).get("orders", 0)
        revenue = revenue_by_nm.get(nm, 0.0)

        # Корректное разделение Удержаний на реклама vs прочее:
        #
        #  - ad_cost = /adv/v3/fullstats (wb_ad_stats_daily) per nm — это
        #    ТОЧНАЯ сумма рекламных трат, которую WB отдаёт через advert API.
        #  - other_deductions = Удержания.deduction − total_ad_cost — остаток
        #    Удержаний, не покрытый рекламой (Подписка Джем, аренда PVZ,
        #    компенсации и пр.). Этого breakdown WB через API не отдаёт,
        #    отдаёт только в UI кабинета (Финансы → Детализация удержаний).
        #    Распределяем pro-rata по продажам.
        #
        # Сумма (ad_cost + other_deductions) = Удержания_total ⇒ итог в
        # expenses_for_tax совпадает с тем, что WB реально списал.
        ad_cost = ad_by_nm.get(nm, {}).get("ad_cost", 0.0)
        other_deductions = other_deductions_total * share_by_sold(nm)
        ext_per_sku = ext_ad_by_nm.get(nm, 0.0)
        ext_brand = brand_share_for(nm)
        ext_total = ext_per_sku + ext_brand
        marketing_total = ad_cost + ext_total + other_deductions
        per_order_marketing = marketing_total / orders if orders > 0 else 0.0

        unit_cogs = cost_for_date(cogs_lookup, nm, midpoint)

        # Real per-unit payout from report_detail (after commission, acquiring,
        # delivery, storage, penalties — same as WB cabinet «к перечислению»).
        # Falls back to wb_sales.for_pay only if report_detail hasn't arrived.
        rd = rd_metrics_by_nm.get(nm)
        if rd is not None and units_sold > 0 and rd["payout"] > 0:
            unit_revenue_net = rd["payout"] / units_sold
            payout_source = "report_detail"
        elif units_sold > 0:
            unit_revenue_net = for_pay / units_sold
            payout_source = "sales_feed"
        else:
            unit_revenue_net = 0.0
            payout_source = "none"

        unit_margin = unit_revenue_net - unit_cogs - per_order_marketing
        unit_margin_pct = (unit_margin / unit_revenue_net * 100) if unit_revenue_net > 0 else 0.0
        roi = (unit_margin / unit_cogs * 100) if unit_cogs > 0 else 0.0
        # DRR (доля рекламных расходов) — total marketing / revenue
        drr_pct = (marketing_total / revenue * 100) if revenue > 0 else 0.0

        # days-to-stockout from last 14d sales velocity
        velocity_units = await _velocity_14d(session, nm)
        stock = stock_by_nm.get(nm, 0)
        dts = round(stock / velocity_units, 1) if velocity_units > 0 else None

        # Buyout % — та же формула, что на дашборде (metrics._compute_window_kpis):
        #   buyout = (sales − returns) / total_orders × 100,
        # где total_orders = активные + отменённые покупателем (всё, что попало
        # в wb_orders), а числитель — net (sales-feed minus returns).
        total_orders = orders_by_nm.get(nm, {}).get("total_orders", 0)
        buyout_pct = (units_sold / total_orders * 100) if total_orders > 0 else 0.0
        turnover_days = (
            round(stock * days_back / units_sold, 1) if units_sold > 0 else None
        )

        # ── Полная P&L разбивка per nm как в Excel ──
        rd_data = rd_metrics_by_nm.get(nm, {})
        rev_sale_rd = rd_data.get("rev_sale", 0.0)
        rev_return_rd = rd_data.get("rev_return", 0.0)
        revenue_net_rd = rd_data.get("revenue_net", 0.0)
        # Acquiring выделяем как отдельное поле (чтобы comission_wb совпадал
        # с P&L и WB-кабинетом, где эквайринг показан отдельно).
        acquiring_net = rd_data.get("acquiring_net", 0.0)
        commission_wb = rd_data.get("commission_wb", 0.0) - acquiring_net
        delivery_rd = rd_data.get("delivery", 0.0)
        # Хранение: предпочитаем точные данные из WB Analytics
        # `/api/v1/paid_storage` (синхронятся ежедневно — таблица
        # wb_paid_storage). НЕ прибавляем rd_data.storage — paid_storage уже
        # содержит полную сумму per nm. Если paid_storage пуст за период —
        # fallback на пропорциональное распределение storage_fee из RD.
        if has_paid_storage_data:
            storage_rd = paid_storage_by_nm.get(nm, 0.0)
        else:
            storage_rd = rd_data.get("storage", 0.0) + storage_unalloc * share_by_stock(nm)
        penalty_rd = rd_data.get("penalty", 0.0)
        # Платная приёмка: WB кладёт сумму в ppvz_vw на rows без nm_id —
        # распределяем пропорционально продажам.
        acceptance_fee_rd = (
            rd_data.get("acceptance_fee", 0.0)
            + acceptance_unalloc * share_by_sold(nm)
        )
        # Удержания (Удержание) теперь идут как реклама через ad_cost выше,
        # отдельно тут не учитываем (иначе double-count в expenses_for_tax).
        # Поле deduction оставляем в output для прозрачности — пусть UI
        # видит, что именно зашло в marketing.
        deduction_rd = deduction_unalloc * share_by_sold(nm)
        loyalty_writeoff_rd = (
            rd_data.get("loyalty_writeoff", 0.0)
            + loyalty_unalloc * share_by_sold(nm)
        )
        acquiring_correction_rd = rd_data.get("acquiring_correction", 0.0)
        ppvz_return_rd = rd_data.get("ppvz_return", 0.0)
        rd_units_sale = rd_data.get("rd_units_sale", 0)

        # COGS total (для распределения по проданным единицам).
        cogs_total = unit_cogs * units_sold

        # Налог per nm — используем _compute_tax с локальным P&L.
        # Расходы для базы налога = себестоимость + комиссия + логистика +
        # хранение + штрафы + платная приёмка + списание баллов + коррекция
        # эквайринга + реклама. (Так же как build_pnl собирает operating
        # expenses для УСН 15%/ОСНО.)
        if vat_payer and vat_rate > 0:
            vat_nm = revenue_net_rd - revenue_net_rd / (1 + vat_rate / 100.0)
        else:
            vat_nm = 0.0
        revenue_after_vat_nm = revenue_net_rd - vat_nm
        expenses_for_tax = (
            cogs_total
            + commission_wb
            + acquiring_net
            + delivery_rd
            + storage_rd
            + penalty_rd
            + acceptance_fee_rd
            + loyalty_writeoff_rd
            + acquiring_correction_rd
            + marketing_total
        )
        # Tax base = retail_amount net (Продажа − Возврат). Это WB-сторонняя
        # «Стоимость продажи» из УПД для ФНС — юридически корректная база
        # для УСН/АУСН-доход. Точно совпадает с Excel клиента (см. AV колонку).
        retail_amt_net_nm = rd_data.get("retail_amt_net", 0.0)
        tax_nm = _compute_tax(
            tax_system,
            revenue_net=revenue_net_rd,
            revenue_after_vat=revenue_after_vat_nm,
            expenses=expenses_for_tax,
            tax_rate=tax_rate,
            tax_min_rate=tax_min_rate,
            reduce_by_insurance=reduce_by_insurance,
            cash_income=retail_amt_net_nm,
        )

        # Чистая прибыль per nm (после налога).
        net_profit = revenue_after_vat_nm - expenses_for_tax - tax_nm
        profitability_pct = (
            (net_profit / revenue_net_rd * 100) if revenue_net_rd > 0 else 0.0
        )

        items.append(
            {
                "nm_id": nm,
                "vendor_code": prod.vendor_code if prod else None,
                "subject": prod.subject if prod else None,
                "brand": prod.brand if prod else None,
                "photo_url": prod.photo_url if prod else None,
                "is_archived": bool(prod.is_archived) if prod else False,
                # Sales feed counters (быстрая аналитика):
                # «Заказы» = ВСЕ заказы за период (active + отменённые покупателем).
                # Это та же база, что используется на дашборде для расчёта buyout%.
                "orders": total_orders,
                # active_orders сохраняется для совместимости (кому нужно отдельно).
                "active_orders": orders,
                "total_orders": total_orders,
                # units_sold = sales − returns (НЕТТО). Может быть отрицательным
                # если возвраты прилетели из заказов сделанных ДО окна. Для
                # «брутто-продаж» и «возвратов» отдельные поля ниже — UI
                # показывает обе цифры, чтобы −1 не выглядел как баг.
                "units_sold": units_sold,
                "units_sold_gross": gross_units,
                "units_returned": returns_count,
                "revenue": revenue,
                "for_pay": for_pay,
                "avg_price": round(avg_price, 2),
                "buyout_pct": round(buyout_pct, 2),
                "commission_pct": round(commission_pct, 2),
                # Real WB-cabinet finances per nm (из report_detail):
                "rev_sale": round(rev_sale_rd, 2),
                "rev_return": round(rev_return_rd, 2),
                "ppvz_return": round(ppvz_return_rd, 2),
                "commission_wb": round(commission_wb, 2),
                "acquiring": round(acquiring_net, 2),
                "delivery": round(delivery_rd, 2),
                "storage": round(storage_rd, 2),
                "penalty": round(penalty_rd, 2),
                "acceptance_fee": round(acceptance_fee_rd, 2),
                "loyalty_writeoff": round(loyalty_writeoff_rd, 2),
                "acquiring_correction": round(acquiring_correction_rd, 2),
                "deduction": round(deduction_rd, 2),
                "other_deductions": round(other_deductions, 2),
                "rd_units_sale": rd_units_sale,
                # Marketing
                "ad_cost": round(ad_cost, 2),
                "external_ad_cost": round(ext_total, 2),
                "ad_per_order": round(per_order_marketing, 2),
                "drr_pct": round(drr_pct, 2),
                # COGS / margin
                "cogs_unit": round(unit_cogs, 2),
                "cogs_total": round(cogs_total, 2),
                "margin_unit": round(unit_margin, 2),
                "margin_pct": round(unit_margin_pct, 2),
                "roi_pct": round(roi, 2),
                # Налог + чистая прибыль
                "tax": round(tax_nm, 2),
                "vat": round(vat_nm, 2),
                "net_profit": round(net_profit, 2),
                "profitability_pct": round(profitability_pct, 2),
                # ── Прогноз «до выкупа»: проекция маржи на ВСЕ заказы периода ──
                # если бы они выкупились по историческому % (то есть сразу
                # покажи сколько ты «уже заработал» по orders, не дожидаясь
                # 2-недельного лага report_detail).
                #
                # forecast_units = total_orders × buyout_pct / 100
                # forecast_revenue = forecast_units × avg_price
                # forecast_margin = forecast_revenue × (1 − commission_pct/100)
                #                   − forecast_units × cogs_unit − ad_cost
                #
                # Для закрытых периодов (orders ≈ sales × 100/buyout_pct)
                # forecast почти равен фактическому margin. Для свежих —
                # выше факта на ту часть orders, что ещё не выкупилась.
                **(
                    lambda fu, fr, fc, fm: {
                        "forecast_units": round(fu, 2),
                        "forecast_revenue": round(fr, 2),
                        "forecast_commission": round(fc, 2),
                        "forecast_margin": round(fm, 2),
                    }
                )(
                    total_orders * buyout_pct / 100.0,
                    total_orders * buyout_pct / 100.0 * (avg_price or 0),
                    total_orders * buyout_pct / 100.0 * (avg_price or 0) * commission_pct / 100.0,
                    (
                        total_orders * buyout_pct / 100.0 * (avg_price or 0)
                        * (1.0 - commission_pct / 100.0)
                        - total_orders * buyout_pct / 100.0 * unit_cogs
                        - ad_cost
                    ),
                ),
                # Stock
                "stock": stock,
                "in_way_to_client": in_way_by_nm.get(nm, {}).get("to_client", 0),
                "in_way_from_client": in_way_by_nm.get(nm, {}).get("from_client", 0),
                "turnover_days": turnover_days,
                "days_to_stockout": dts,
            }
        )

    items.sort(key=lambda x: x["rev_sale"] or x["revenue"], reverse=True)
    return {
        "days_back": days_back,
        "start_date": start.date().isoformat(),
        "end_date": (end - timedelta(days=1)).date().isoformat(),
        "tax_system": tax_system,
        "tax_rate": tax_rate,
        "vat_payer": vat_payer,
        "vat_rate": vat_rate,
        "items": items,
    }


async def _velocity_14d(session: AsyncSession, nm_id: int) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    row = (
        await session.execute(
            select(func.coalesce(func.sum(case((WbSale.is_return, -1), else_=1)), 0)).where(
                WbSale.nm_id == nm_id,
                WbSale.sale_dt >= start,
                WbSale.sale_dt < end,
            )
        )
    ).scalar_one()
    return float(row or 0) / 14.0
