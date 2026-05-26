"""Автосверка 17 правил TrueStats art.74754 (TASK-LEAD-137).

Source of truth для каждой метрики — формула из `RECON_GUIDE.md`. Возвращает
значения для одной недели по `wb_report_detail`, бренд-фильтр опционально.

Маппинги полей подтверждены прецедент-сверкой на vipryn@gmail.com 2026-05-26:
- TS «Размер кВВ, %» (xlsx col X) → `commission_percent` (TASK-LEAD-132)
- TS «Вайлдберриз реализовал Товар (Пр)» (xlsx col P) → `retail_amount` (TASK-LEAD-133)
- Эквайринг — split (sale − return), не общий SUM (TASK-LEAD-134)

Метрики 9-11 (реклама, кол-во заказов, сумма заказов) — **из других таблиц**
(`wb_ad_stats_daily` / `wb_orders`), считаются отдельно ниже.

Метрики 8 и 17 (Прочие удержания, Компенсации) пока показываются raw — fix
ожидается в TASK-LEAD-135 / TASK-LEAD-136.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbAdStatsDaily, WbOrder, WbReportDetail


METRIC_GROUPS: dict[str, str] = {
    "sales": "Продажи и комиссии",
    "logistics": "Логистика, хранение, штрафы",
    "deductions": "Удержания",
    "ads_orders": "Реклама и заказы",
    "advanced": "Расширенные метрики",
}


async def compute_truestats_metrics(
    session: AsyncSession,
    *,
    tenant_id: int,
    week_start: date,
    week_end: date,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """17 метрик TS для одной недели.

    `week_end` exclusive (как везде в проекте). Если brands=None — company-scope.
    """
    # Базовый фильтр на wb_report_detail: по rr_dt принадлежит [week_start, week_end)
    # — это финансовая методология (как в TS).
    base_where = [
        WbReportDetail.tenant_id == tenant_id,
        WbReportDetail.rr_dt >= week_start,
        WbReportDetail.rr_dt < week_end,
    ]
    if brands is not None:
        if not brands:
            # Manager без брендов — вернём пустые значения чтобы не падать.
            return _empty_response(week_start, week_end)
        base_where.append(WbReportDetail.nm_id.in_(
            select(Product.nm_id).where(
                Product.tenant_id == tenant_id,
                Product.brand.in_(list(brands)),
            )
        ))

    sale_filter = WbReportDetail.supplier_oper_name == "Продажа"
    return_filter = WbReportDetail.supplier_oper_name == "Возврат"

    # Универсальный сум-по-условию sale минус return.
    def sale_minus_return(field):
        return func.sum(
            case((sale_filter, field), (return_filter, -field), else_=0)
        )

    stmt = select(
        # 1. Сумма продаж = Σ ppvz_for_pay для Продажа
        func.sum(case((sale_filter, WbReportDetail.ppvz_for_pay), else_=0)).label("sales_sum"),
        # 2. К перечислению = sale − return
        sale_minus_return(WbReportDetail.ppvz_for_pay).label("to_seller"),
        # 3. Логистика
        func.sum(WbReportDetail.delivery_rub).label("logistics"),
        # 4. Хранение
        func.sum(WbReportDetail.storage_fee).label("storage"),
        # 5. Платная приёмка
        func.sum(WbReportDetail.paid_acceptance).label("paid_acceptance"),
        # 6. Кол-во продаж = qty(sale) - qty(return)
        sale_minus_return(WbReportDetail.quantity).label("qty"),
        # 7. Штрафы
        func.sum(WbReportDetail.penalty).label("penalty"),
        # 8. Прочие удержания — raw `deduction` (TASK-LEAD-135 разложит на 4 компонента)
        func.sum(WbReportDetail.deduction).label("deduction"),
        # 12. Реализация = retail_with_disc sale - return
        sale_minus_return(WbReportDetail.retail_price_withdisc_rub).label("realization"),
        # 14. Номинальная комиссия = Σ retail × commission_percent / 100 (TASK-LEAD-132)
        sale_minus_return(
            WbReportDetail.retail_price * WbReportDetail.commission_percent / 100
        ).label("nominal_commission"),
        # 15. СПП = retail − retail_amount (TASK-LEAD-133)
        sale_minus_return(
            WbReportDetail.retail_price - WbReportDetail.retail_amount
        ).label("spp"),
        # 16. Эквайринг split (TASK-LEAD-134) — sale − return, не общий SUM
        sale_minus_return(WbReportDetail.acquiring_fee).label("acquiring"),
        # Метаинформация
        func.count(func.distinct(WbReportDetail.realization_id)).label("realization_ids_count"),
        func.count().label("rows_count"),
    ).where(and_(*base_where))

    row = (await session.execute(stmt)).one()

    sales_sum = float(row.sales_sum or 0)
    to_seller = float(row.to_seller or 0)
    # 13. Комиссия (общая) = Реализация − К перечислению (формула TS rule 13)
    realization = float(row.realization or 0)
    commission_total = realization - to_seller

    # Метрики 9-11: реклама и заказы — из других таблиц
    # 9. Реклама — wb_ad_stats_daily (фактические списания)
    ads_where = [
        WbAdStatsDaily.tenant_id == tenant_id,
        WbAdStatsDaily.stat_date >= week_start,
        WbAdStatsDaily.stat_date < week_end,
    ]
    if brands is not None:
        ads_where.append(WbAdStatsDaily.nm_id.in_(
            select(Product.nm_id).where(
                Product.tenant_id == tenant_id, Product.brand.in_(list(brands))
            )
        ))
    ads_row = (await session.execute(
        select(func.coalesce(func.sum(WbAdStatsDaily.sum), 0).label("ad_cost"))
        .where(and_(*ads_where))
    )).one()
    ad_cost = float(ads_row.ad_cost or 0)

    # 10-11. Заказы — wb_orders, фильтр по order_dt, исключая отменённые
    orders_where = [
        WbOrder.tenant_id == tenant_id,
        WbOrder.order_dt >= datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc),
        WbOrder.order_dt < datetime.combine(week_end, datetime.min.time(), tzinfo=timezone.utc),
        WbOrder.is_cancel.is_(False),
    ]
    if brands is not None:
        orders_where.append(WbOrder.brand.in_(list(brands)))
    orders_row = (await session.execute(
        select(
            func.count().label("orders_count"),
            func.coalesce(func.sum(WbOrder.price_with_disc), 0).label("orders_sum"),
        ).where(and_(*orders_where))
    )).one()
    orders_count = int(orders_row.orders_count or 0)
    orders_sum = float(orders_row.orders_sum or 0)

    # Собираем 17 метрик в линейный список — фронт рендерит таблицу.
    metrics = [
        # group "sales"
        _metric(1, "sales", "Сумма продаж",
                "Σ К перечислению Продавцу (doc=Продажа, oper=Продажа)",
                sales_sum, status="ok"),
        _metric(2, "sales", "К перечислению",
                "Σ К перечислению (Продажа − Возврат)",
                to_seller, status="ok"),
        _metric(12, "sales", "Реализация",
                "Σ retail с учётом скидки (Продажа − Возврат)",
                realization, status="ok"),
        _metric(13, "sales", "Комиссия общая",
                "Реализация − К перечислению",
                commission_total, status="ok"),
        _metric(14, "sales", "Номинальная комиссия МП",
                "Σ retail × commission_percent / 100 (Продажа − Возврат)",
                float(row.nominal_commission or 0), status="ok"),
        _metric(15, "sales", "СПП",
                "Σ (retail − retail_amount) (Продажа − Возврат)",
                float(row.spp or 0), status="ok"),
        _metric(16, "sales", "Эквайринг (split)",
                "Σ acquiring_fee (Продажа − Возврат)",
                float(row.acquiring or 0), status="ok"),
        # group "logistics"
        _metric(3, "logistics", "Логистика",
                "Σ Услуги по доставке (delivery_rub)",
                float(row.logistics or 0), status="ok"),
        _metric(4, "logistics", "Хранение",
                "Σ storage_fee (см. также Аналитика → Платное хранение)",
                float(row.storage or 0), status="ok"),
        _metric(5, "logistics", "Платная приёмка",
                "Σ paid_acceptance (см. Операции при приемке)",
                float(row.paid_acceptance or 0), status="ok"),
        _metric(7, "logistics", "Штрафы",
                "Σ penalty",
                float(row.penalty or 0), status="ok"),
        # group "deductions"
        _metric(8, "deductions", "Прочие удержания",
                "Σ deduction (raw — TASK-LEAD-135 разложит на 4 компонента − 14 исключений)",
                float(row.deduction or 0), status="gap_135"),
        _metric(17, "deductions", "Компенсации",
                "3-этапный TS-процесс (TASK-LEAD-136)",
                0.0, status="gap_136"),
        # group "ads_orders"
        _metric(9, "ads_orders", "Реклама ВБ.Продвижение",
                "Σ sum по wb_ad_stats_daily (фактические списания)",
                ad_cost, status="ok"),
        _metric(10, "ads_orders", "Кол-во заказов",
                "COUNT wb_orders WHERE order_dt in [week, week+7) AND NOT is_cancel",
                orders_count, status="ok", is_count=True),
        _metric(11, "ads_orders", "Сумма заказов",
                "Σ price_with_disc по wb_orders",
                orders_sum, status="ok"),
        # group "advanced" (метрика 6 — qty)
        _metric(6, "advanced", "Кол-во проданных шт.",
                "Σ quantity (Продажа − Возврат)",
                int(row.qty or 0), status="ok", is_count=True),
    ]

    # Realization IDs которые попали в эту неделю — может быть несколько.
    realization_ids_stmt = select(func.distinct(WbReportDetail.realization_id)).where(and_(*base_where))
    realization_ids = sorted([
        int(rid) for rid in (await session.execute(realization_ids_stmt)).scalars().all()
        if rid is not None
    ])

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "realization_ids": realization_ids,
        "rows_count": int(row.rows_count or 0),
        "scope": "brands" if brands is not None else "company",
        "metrics": metrics,
        "groups": METRIC_GROUPS,
    }


def _metric(
    rule_number: int,
    group: str,
    name: str,
    formula: str,
    value: float,
    *,
    status: str,
    is_count: bool = False,
) -> dict[str, Any]:
    """Возвращает структуру одной метрики для UI."""
    return {
        "rule_number": rule_number,
        "group": group,
        "name": name,
        "formula": formula,
        "our_value": value,
        "status": status,  # ok | gap_NNN
        "is_count": is_count,
    }


def _empty_response(week_start: date, week_end: date) -> dict[str, Any]:
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "realization_ids": [],
        "rows_count": 0,
        "scope": "brands",
        "metrics": [],
        "groups": METRIC_GROUPS,
    }


def last_closed_week() -> tuple[date, date]:
    """Возвращает [start, end) последней закрытой WB-недели (пн-вс).

    Сегодня вторник → закрытая неделя = пн-вс на прошлой неделе.
    Используется как default для autocomplete на UI.
    """
    today = date.today()
    # weekday(): пн=0, вс=6
    days_since_monday = today.weekday()
    this_week_monday = today - timedelta(days=days_since_monday)
    last_week_monday = this_week_monday - timedelta(days=7)
    last_week_sunday_excl = this_week_monday  # exclusive
    return last_week_monday, last_week_sunday_excl
