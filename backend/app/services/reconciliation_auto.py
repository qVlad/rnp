"""Автосверка 17 правил TrueStats art.74754 (TASK-LEAD-137).

Source of truth для каждой метрики — формула из `RECON_GUIDE.md`. Возвращает
значения для одной недели по `wb_report_detail`, бренд-фильтр опционально.

Маппинги полей подтверждены прецедент-сверкой на vipryn@gmail.com 2026-05-26:
- TS «Размер кВВ, %» (xlsx col X) → `commission_percent` (TASK-LEAD-132)
- TS «Вайлдберриз реализовал Товар (Пр)» (xlsx col P) → `retail_amount` (TASK-LEAD-133)
- Эквайринг — split (sale − return), не общий SUM (TASK-LEAD-134)

Метрики 9-11 (реклама, кол-во заказов, сумма заказов) — **из других таблиц**
(`wb_ad_stats_daily` / `wb_orders`), считаются отдельно ниже.

Метрика 8 (Прочие удержания) — TASK-LEAD-135: TS-методология «4 компонента
минус 14 исключений» через blacklist по `bonus_type_name` (рекламные/займовые
сервисы исключаются).
Метрика 17 (Компенсации) — TASK-LEAD-136: 3-этапный TS-процесс через
match по `supplier_oper_name`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbAdStatsDaily, WbOrder, WbReportDetail


# TASK-LEAD-135: keyword-based blacklist на `bonus_type_name`. Если в имени
# bonus-типа содержится любое из ключевых слов — строка ИСКЛЮЧАЕТСЯ из
# «Прочих удержаний» (по методологии TS art.74754 правило 8).
# Подтверждено на vipryn-неделе 2026-05-18..24: 22 990₽ Джем-подписка + 6 902₽
# WB Продвижение — оба должны быть исключены, итого Прочие = 0₽.
DEDUCTION_EXCLUSION_KEYWORDS: tuple[str, ...] = (
    # реклама WB
    "Продвижение",
    "Реклама",
    "Медиа",
    # сторонние сервисы / подписки
    "Джем",
    "Подписк",
    "WB-Тариф",
    # займы
    "Заём",
    "Займ",
    "Погашен",
    # учитывается в других строках
    "Хранение",
    "Эквайринг",
    "Платежные услуги",
    # удержания доставки / возвратные операции (входят в логистику)
    "Возврат брака",
    "Возврат от клиента",
)


# TASK-LEAD-136: 3-этапный TS-процесс для «Компенсаций» (правило 17).
# Stage 1: суммируем `ppvz_for_pay` для строк где supplier_oper_name в этом списке.
COMPENSATIONS_STAGE1_OPERS: tuple[str, ...] = (
    "Компенсация подмененного товара",
    "Возмещение издержек по перевозке/по складским операциям с товаром",
    "Оплата/частичная компенсация брака",
    "Оплата ошибочно удержанной суммы (кладовщик)",
)

# Stage 2: + sale, Stage 3: − return для этих категорий.
COMPENSATIONS_STAGE23_OPERS: tuple[str, ...] = (
    "Оплата потерянного товара",
    "Компенсация ущерба",
    "Добровольная компенсация при возврате",
)


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
    realization_id: int | None = None,
) -> dict[str, Any]:
    """17 метрик TS для одной недели.

    `week_end` exclusive (как везде в проекте). Если brands=None — company-scope.

    `realization_id` (TASK-LEAD-138): если задан — метрики из wb_report_detail
    (правила 1-8, 12-17) считаются ТОЛЬКО по этому отчёту, а не по всей неделе.
    Нужно для точной сверки отчёт-в-отчёт с WB ЛК summary (когда за неделю
    несколько отчётов: основной + корректировки). Реклама/заказы (9,10,11) —
    всегда по неделе (у них нет realization_id).
    """
    # Базовый фильтр на wb_report_detail. По умолчанию — по rr_dt неделе
    # (финансовая методология TS). Если задан realization_id — по нему
    # (точная сверка с конкретным WB-отчётом).
    if realization_id is not None:
        base_where = [
            WbReportDetail.tenant_id == tenant_id,
            WbReportDetail.realization_id == realization_id,
        ]
    else:
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
        # 1. Сумма продаж = Σ retail_amount «Вайлдберриз реализовал» (Продажа − Возврат).
        # Подтверждено на vipryn 2026-05-18..24: совпадает с WB ЛК totalSale=1 496 155.38.
        sale_minus_return(WbReportDetail.retail_amount).label("sales_sum"),
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
        # 8. Прочие удержания (RAW) — для совместимости / отображения «было до 135»
        func.sum(WbReportDetail.deduction).label("deduction_raw"),
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

    # TASK-LEAD-135: «Прочие удержания» по методологии TS — фильтрация по
    # `bonus_type_name` через blacklist. Pure SQL: запрос ниже + summing python-side
    # с проверкой keyword'ов (не делаем 14 LIKE-условий, проще итерировать).
    deduction_breakdown_stmt = (
        select(
            WbReportDetail.bonus_type_name,
            WbReportDetail.supplier_oper_name,
            func.sum(WbReportDetail.deduction).label("amount"),
        )
        .where(and_(*base_where))
        .where(WbReportDetail.deduction != 0)
        .group_by(WbReportDetail.bonus_type_name, WbReportDetail.supplier_oper_name)
    )
    deduction_other_ts = 0.0
    deduction_excluded = 0.0
    deduction_excluded_by_keyword: dict[str, float] = {}
    for ded_row in (await session.execute(deduction_breakdown_stmt)).all():
        amt = float(ded_row.amount or 0)
        bonus = (ded_row.bonus_type_name or "")
        oper = (ded_row.supplier_oper_name or "")
        # Если supplier_oper_name = «Удержание» И bonus_type_name НЕ содержит
        # ни одного исключающего keyword'а — это «прочее удержание» по TS.
        matched_kw = next(
            (kw for kw in DEDUCTION_EXCLUSION_KEYWORDS if kw.lower() in bonus.lower()),
            None,
        )
        if oper == "Удержание" and matched_kw is None:
            deduction_other_ts += amt
        elif matched_kw is not None:
            deduction_excluded += amt
            deduction_excluded_by_keyword[matched_kw] = (
                deduction_excluded_by_keyword.get(matched_kw, 0.0) + amt
            )

    # TASK-LEAD-136: «Компенсации» — 3-этапный TS-процесс.
    comp_stage1 = (await session.execute(
        select(func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0))
        .where(and_(*base_where))
        .where(WbReportDetail.supplier_oper_name.in_(list(COMPENSATIONS_STAGE1_OPERS)))
    )).scalar() or 0
    comp_stage2 = (await session.execute(
        select(func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0))
        .where(and_(*base_where))
        .where(WbReportDetail.supplier_oper_name.in_(list(COMPENSATIONS_STAGE23_OPERS)))
        .where(WbReportDetail.doc_type_name == "Продажа")
    )).scalar() or 0
    comp_stage3 = (await session.execute(
        select(func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0))
        .where(and_(*base_where))
        .where(WbReportDetail.supplier_oper_name.in_(list(COMPENSATIONS_STAGE23_OPERS)))
        .where(WbReportDetail.doc_type_name == "Возврат")
    )).scalar() or 0
    compensations_total = float(comp_stage1) + float(comp_stage2) - float(comp_stage3)

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
        select(func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"))
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
                "Σ retail_amount «Вайлдберриз реализовал» (Продажа − Возврат) = WB totalSale",
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
        # group "deductions" — для СВЕРКИ с WB our_value = raw deduction (так
        # WB показывает «Удержания» в paidWithholdingSum). TS-разбивка
        # (чистые прочие без рекламы/Джем) — в meta, видна в expandable detail.
        _metric(8, "deductions", "Прочие удержания (raw = WB)",
                "Σ deduction (как WB paidWithholdingSum; TS-фильтр в детализации)",
                float(row.deduction_raw or 0), status="ok",
                meta={
                    "raw_total": float(row.deduction_raw or 0),
                    "ts_clean": deduction_other_ts,
                    "excluded_total": deduction_excluded,
                    "excluded_by_keyword": deduction_excluded_by_keyword,
                }),
        # TASK-LEAD-136: 3-этапный TS-процесс
        _metric(17, "deductions", "Компенсации (3 этапа TS)",
                f"Σ stage1 ({len(COMPENSATIONS_STAGE1_OPERS)} oper) + sale stage2 − return stage3",
                compensations_total, status="ok",
                meta={
                    "stage1": float(comp_stage1),
                    "stage2_sale": float(comp_stage2),
                    "stage3_return": float(comp_stage3),
                }),
        # group "ads_orders" — НЕ из отчёта реализации! Источник WB — другие
        # разделы ЛК (Продвижение / Воронка). xlsx и summary их не содержат,
        # поэтому WB-колонка автозаполнению не подлежит → ручной ввод.
        _metric(9, "ads_orders", "Реклама ВБ.Продвижение",
                "Σ sum по wb_ad_stats_daily (фактические списания)",
                ad_cost, status="ok",
                meta={"wb_source": "ЛК WB → Продвижение → Финансы (фактические списания за период)"}),
        _metric(10, "ads_orders", "Кол-во заказов",
                "COUNT wb_orders WHERE order_dt in [week, week+7) AND NOT is_cancel",
                orders_count, status="ok", is_count=True,
                meta={"wb_source": "ЛК WB → Аналитика → Воронка продаж (столбец «Заказали товаров в шт»)"}),
        _metric(11, "ads_orders", "Сумма заказов",
                "Σ price_with_disc по wb_orders",
                orders_sum, status="ok",
                meta={"wb_source": "ЛК WB → Аналитика → Воронка продаж (столбец «Заказали на сумму»)"}),
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
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Возвращает структуру одной метрики для UI."""
    out = {
        "rule_number": rule_number,
        "group": group,
        "name": name,
        "formula": formula,
        "our_value": value,
        "status": status,  # ok | gap_NNN
        "is_count": is_count,
    }
    if meta is not None:
        out["meta"] = meta
    return out


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
