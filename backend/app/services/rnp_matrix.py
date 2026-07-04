"""РНП-матрица «метрики × дни» (TASK-DEV-094) — аналог TrueStats «Модуль РНП».

30+ строк-метрик по дням периода. Все данные — из уже синкаемых таблиц
(нулевая новая WB-нагрузка): wb_orders (факт заказы), wb_sales (факт выкупы),
wb_funnel_daily (% выкупа терминальный), wb_ad_stats_daily + wb_ad_campaigns
(реклама с разбивкой по типам кампаний), wb_stock_snapshots (остатки 4 вида),
wb_card_price (СПП), summary_metrics (коэффициенты прибыли периода с
опер.расходами), metric_plans (план-строки).

Типы кампаний WB (по факту в БД: 4,5,6,7,9):
6 = Поиск; 4/5/7/8 = Полки+Каталог (каталог/карточка/главная/авто);
9 = Единая (аукцион).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MetricPlan,
    MetricPlanTarget,
    RnpSkuSelection,
    WbAdCampaign,
    WbAdStatsDaily,
    WbCardPrice,
    WbFunnelDaily,
    WbOrder,
    WbSale,
    WbStockSnapshot,
)

_SEARCH_TYPES = (6,)
_SHELF_TYPES = (4, 5, 7, 8)
_UNIFIED_TYPES = (9,)


def _f(v: Any) -> float:
    return float(v or 0)


async def get_rnp_nm_scope(
    session: AsyncSession, nm_scope: set[int] | None
) -> set[int] | None:
    """Пересечь глобальный nm-фильтр с «Настройками РНП» (enabled SKU).

    Нет строк выбора у tenant'а → показываем всё (None или глобальный фильтр).
    """
    sel_rows = (
        await session.execute(
            select(RnpSkuSelection.nm_id, RnpSkuSelection.enabled)
        )
    ).all()
    if not sel_rows:
        return nm_scope
    enabled = {int(nm) for nm, en in sel_rows if en}
    if nm_scope is None:
        return enabled
    return nm_scope & enabled


async def build_rnp_matrix(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    nm_scope: set[int] | None = None,
) -> dict[str, Any]:
    days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    day_keys = [d.isoformat() for d in days]
    n_days = len(days)

    def nm_pred(col):
        return [col.in_(nm_scope)] if nm_scope is not None else []

    # ── Факт заказы по дням (wb_orders, «Лента», без отменённых) ──────────
    orows = (
        await session.execute(
            select(
                func.date(WbOrder.order_dt).label("d"),
                func.count(WbOrder.srid).label("cnt"),
                func.coalesce(func.sum(func.coalesce(WbOrder.price_with_disc, WbOrder.total_price)), 0).label("amt"),
            )
            .where(
                func.date(WbOrder.order_dt) >= date_from,
                func.date(WbOrder.order_dt) <= date_to,
                WbOrder.is_cancel.is_(False),
                *nm_pred(WbOrder.nm_id),
            )
            .group_by(func.date(WbOrder.order_dt))
        )
    ).all()
    orders_cnt = {r.d.isoformat(): int(r.cnt) for r in orows}
    orders_rub = {r.d.isoformat(): _f(r.amt) for r in orows}

    # ── Факт выкупы по дням (wb_sales) — для ДРР по продажам ──────────────
    sret = WbSale.is_return
    salrows = (
        await session.execute(
            select(
                func.date(WbSale.sale_dt).label("d"),
                func.coalesce(func.sum(case((~sret, WbSale.price_with_disc), else_=0)), 0).label("amt"),
                func.coalesce(func.sum(case((~sret, 1), else_=0)), 0).label("cnt"),
            )
            .where(
                func.date(WbSale.sale_dt) >= date_from,
                func.date(WbSale.sale_dt) <= date_to,
                *nm_pred(WbSale.nm_id),
            )
            .group_by(func.date(WbSale.sale_dt))
        )
    ).all()
    sales_rub = {r.d.isoformat(): _f(r.amt) for r in salrows}

    # ── % выкупа терминальный по дням (Воронка, DEV-087) ──────────────────
    frows = (
        await session.execute(
            select(
                WbFunnelDaily.dt,
                func.coalesce(func.sum(WbFunnelDaily.buyouts_count), 0).label("b"),
                func.coalesce(func.sum(WbFunnelDaily.cancel_count), 0).label("c"),
            )
            .where(WbFunnelDaily.dt >= date_from, WbFunnelDaily.dt <= date_to,
                   *nm_pred(WbFunnelDaily.nm_id))
            .group_by(WbFunnelDaily.dt)
        )
    ).all()
    buyout_by_day: dict[str, float] = {}
    b_sum = c_sum = 0
    for r in frows:
        b, c = int(r.b), int(r.c)
        b_sum += b
        c_sum += c
        if b + c > 0:
            buyout_by_day[r.dt.isoformat()] = b / (b + c) * 100
    buyout_avg = (b_sum / (b_sum + c_sum) * 100) if (b_sum + c_sum) > 0 else 0.0

    # ── Средняя СПП (для цены после СПП / скидки МП) ──────────────────────
    spp_rows = (
        await session.execute(
            select(func.avg(WbCardPrice.observed_spp_pct)).where(
                WbCardPrice.observed_spp_pct.isnot(None),
                *([WbCardPrice.nm_id.in_(nm_scope)] if nm_scope is not None else []),
            )
        )
    ).scalar()
    spp_avg = _f(spp_rows)

    # ── Остатки 4 вида по дням (последний снапшот дня) ────────────────────
    strows = (
        await session.execute(
            select(
                func.date(WbStockSnapshot.snapshot_dt).label("d"),
                func.max(WbStockSnapshot.snapshot_dt).label("last_dt"),
            )
            .where(
                func.date(WbStockSnapshot.snapshot_dt) >= date_from,
                func.date(WbStockSnapshot.snapshot_dt) <= date_to,
            )
            .group_by(func.date(WbStockSnapshot.snapshot_dt))
        )
    ).all()
    last_snap_per_day = {r.d.isoformat(): r.last_dt for r in strows}
    stock_q: dict[str, int] = {}
    stock_to: dict[str, int] = {}
    stock_from: dict[str, int] = {}
    if last_snap_per_day:
        snaps = list(last_snap_per_day.values())
        qrows = (
            await session.execute(
                select(
                    func.date(WbStockSnapshot.snapshot_dt).label("d"),
                    func.coalesce(func.sum(WbStockSnapshot.quantity), 0).label("q"),
                    # НЕ label("t"): Row.t в SQLAlchemy 2 — зарезервированный
                    # аксессор «row as tuple», r.t вернёт весь кортеж → 500.
                    func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("to_c"),
                    func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("from_c"),
                )
                .where(WbStockSnapshot.snapshot_dt.in_(snaps), *nm_pred(WbStockSnapshot.nm_id))
                .group_by(func.date(WbStockSnapshot.snapshot_dt))
            )
        ).all()
        for r in qrows:
            k = r.d.isoformat()
            stock_q[k] = int(r.q)
            stock_to[k] = int(r.to_c)
            stock_from[k] = int(r.from_c)

    # ── Реклама по дням с типами кампаний ─────────────────────────────────
    adrows = (
        await session.execute(
            select(
                WbAdStatsDaily.stat_date.label("d"),
                WbAdCampaign.type.label("ctype"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
                func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("views"),
                func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("clicks"),
                func.coalesce(func.sum(WbAdStatsDaily.atbs), 0).label("atbs"),
                func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("ad_orders"),
                func.coalesce(func.sum(WbAdStatsDaily.shks), 0).label("shks"),
            )
            .join(WbAdCampaign, WbAdCampaign.advert_id == WbAdStatsDaily.advert_id, isouter=True)
            .where(
                WbAdStatsDaily.stat_date >= date_from,
                WbAdStatsDaily.stat_date <= date_to,
                *nm_pred(WbAdStatsDaily.nm_id),
            )
            .group_by(WbAdStatsDaily.stat_date, WbAdCampaign.type)
        )
    ).all()
    ad: dict[str, dict[str, float]] = {}
    for r in adrows:
        k = r.d.isoformat()
        slot = ad.setdefault(k, {"spent": 0, "search": 0, "shelf": 0, "unified": 0,
                                 "views": 0, "clicks": 0, "atbs": 0, "ad_orders": 0, "shks": 0})
        spent = _f(r.spent)
        slot["spent"] += spent
        if r.ctype in _SEARCH_TYPES:
            slot["search"] += spent
        elif r.ctype in _SHELF_TYPES:
            slot["shelf"] += spent
        else:  # 9 и неизвестные — Единая
            slot["unified"] += spent
        slot["views"] += _f(r.views)
        slot["clicks"] += _f(r.clicks)
        slot["atbs"] += _f(r.atbs)
        slot["ad_orders"] += _f(r.ad_orders)
        slot["shks"] += _f(r.shks)

    # ── Коэффициенты прибыли (с опер.расходами) из summary-движка ─────────
    # DEV-096 (как TS «Настройки расчёта»): окно усреднения — «7»/«28» дней
    # по последним ПОЛНЫМ календарным неделям (пн-вс) либо «period» (по
    # выбранному периоду матрицы, наше поведение по умолчанию).
    from app.db.models import AppSetting  # noqa: WPS433
    from app.services.summary_metrics import build_summary_report  # noqa: WPS433
    from app.services.tenant_context import get_tenant  # noqa: WPS433

    coef_from, coef_to = date_from, date_to
    tid = get_tenant(session)
    if tid is not None:
        # pitfall #16: AppSetting без tenant-mixin — фильтруем явно.
        window = (
            await session.execute(
                select(AppSetting.value).where(
                    AppSetting.tenant_id == tid,
                    AppSetting.key == "rnp_forecast_window",
                )
            )
        ).scalar_one_or_none()
        if window in ("7", "28"):
            today = date.today()
            last_sunday = today - timedelta(days=today.weekday() + 1)
            coef_to = last_sunday
            coef_from = coef_to - timedelta(days=int(window) - 1)

    summ = await build_summary_report(
        session, start_date=coef_from, end_date=coef_to,
        reporting_mode="operational", nm_scope=nm_scope,
    )
    st = summ["totals"]
    profit_ratio = (st["profit"] / st["sales"]) if st["sales"] else 0.0  # прибыль/₽ продаж
    roi_ratio = (st["roi_pct"] or 0.0)
    cogs_per_sale_rub = (st["cogs"] / st["sales"]) if st["sales"] else 0.0
    opex_per_day = (st["opex"] or 0.0) / n_days if n_days else 0.0

    # ── План-строки из metric_plans, покрывающих дни периода ──────────────
    plan_orders: dict[str, float] = {}
    plan_margin: dict[str, float] = {}
    plans = (
        await session.execute(
            select(MetricPlan).where(
                MetricPlan.started_at <= date_to, MetricPlan.finished_at >= date_from
            )
        )
    ).scalars().all()
    if plans:
        targets = (
            await session.execute(
                select(MetricPlanTarget).where(
                    MetricPlanTarget.plan_id.in_([p.id for p in plans])
                )
            )
        ).scalars().all()
        t_by_plan: dict[int, dict[str, float]] = {}
        for t in targets:
            t_by_plan.setdefault(t.plan_id, {})[t.metric_slug] = _f(t.plan_value)
        for p in plans:
            p_days = (p.finished_at - p.started_at).days + 1
            tp = t_by_plan.get(p.id, {})
            for d in days:
                if p.started_at <= d <= p.finished_at:
                    k = d.isoformat()
                    if "orders" in tp:
                        plan_orders[k] = plan_orders.get(k, 0) + tp["orders"] / p_days
                    if "margin_pct" in tp:
                        plan_margin[k] = tp["margin_pct"]

    # ── Сборка строк ──────────────────────────────────────────────────────
    def series(getter) -> list[float | None]:
        return [getter(k) for k in day_keys]

    def _safe_div(a: float, b: float, mult: float = 1.0) -> float | None:
        return round(a / b * mult, 2) if b else None

    rows: list[dict[str, Any]] = []

    def add(key: str, label: str, group: str, fmt: str, values: list, total: float | None = None):
        vals = [round(v, 2) if isinstance(v, float) else v for v in values]
        if total is None:
            nums = [v for v in vals if isinstance(v, (int, float))]
            total = round(sum(nums), 2) if nums else None
        rows.append({"key": key, "label": label, "group": group, "format": fmt,
                     "values": vals, "total": total})

    fs_units = {k: orders_cnt.get(k, 0) * (buyout_by_day.get(k, buyout_avg) / 100) for k in day_keys}
    fs_rub = {k: orders_rub.get(k, 0.0) * (buyout_by_day.get(k, buyout_avg) / 100) for k in day_keys}
    profit_day = {k: fs_rub[k] * profit_ratio for k in day_keys}

    total_fs_rub = sum(fs_rub.values())
    total_profit = sum(profit_day.values())

    add("forecast_margin_pct", "Прогноз. маржинальность с опер.расходами, %", "Прибыль", "pct",
        [(_safe_div(profit_day[k], fs_rub[k], 100) or 0.0) for k in day_keys],
        _safe_div(total_profit, total_fs_rub, 100) or 0.0)
    add("plan_margin_pct", "План. марж., %", "Прибыль", "pct",
        [plan_margin.get(k, 0.0) for k in day_keys],
        round(sum(plan_margin.values()) / max(len([v for v in plan_margin.values() if v]), 1), 2) if plan_margin else 0.0)
    add("forecast_roi_pct", "ROI с опер.расходами, %", "Прибыль", "pct",
        [(_safe_div(profit_day[k], fs_rub[k] * cogs_per_sale_rub / 1, 100) if fs_rub[k] and cogs_per_sale_rub else 0.0) for k in day_keys],
        roi_ratio)
    add("forecast_profit_unit", "Прогноз. приб. с опер.расходами на 1 ед., ₽", "Прибыль", "rub",
        [(_safe_div(profit_day[k], fs_units[k]) or 0.0) for k in day_keys],
        _safe_div(total_profit, sum(fs_units.values())) or 0.0)
    add("forecast_profit", "Прогноз. приб. с опер.расходами, ₽", "Прибыль", "rub",
        [profit_day[k] for k in day_keys])
    add("opex", "Операционные расходы, ₽", "Прибыль", "rub",
        [opex_per_day for _ in day_keys])
    add("plan_orders", "План. заказы, шт", "Заказы", "num",
        [plan_orders.get(k, 0.0) for k in day_keys])
    add("fact_orders_units", "Факт. заказы, шт", "Заказы", "num",
        [float(orders_cnt.get(k, 0)) for k in day_keys])
    add("fact_orders_rub", "Факт. заказы, ₽", "Заказы", "rub",
        [orders_rub.get(k, 0.0) for k in day_keys])
    add("forecast_sales_units", "Прогноз. продажи, шт", "Заказы", "num",
        [fs_units[k] for k in day_keys])
    add("forecast_sales_rub", "Прогноз. продажи, ₽", "Заказы", "rub",
        [fs_rub[k] for k in day_keys])
    price_before = {k: (_safe_div(orders_rub.get(k, 0.0), orders_cnt.get(k, 0)) or 0.0) for k in day_keys}
    add("price_before_spp", "Цена до СПП, ₽", "Цены", "rub",
        [price_before[k] for k in day_keys],
        _safe_div(sum(orders_rub.values()), sum(orders_cnt.values())) or 0.0)
    add("price_after_spp", "Цена после СПП, ₽", "Цены", "rub",
        [round(price_before[k] * (1 - spp_avg / 100), 2) for k in day_keys],
        round((_safe_div(sum(orders_rub.values()), sum(orders_cnt.values())) or 0.0) * (1 - spp_avg / 100), 2))
    add("mp_discount_pct", "Скидка МП, %", "Цены", "pct",
        [spp_avg for _ in day_keys], round(spp_avg, 2))
    add("stock_all", "Все остатки, шт", "Остатки", "num",
        [float((stock_q.get(k, 0) + stock_to.get(k, 0) + stock_from.get(k, 0)) or 0) for k in day_keys],
        None)
    add("stock_wh", "Остатки, шт", "Остатки", "num",
        [float(stock_q.get(k, 0)) for k in day_keys], None)
    add("stock_from_client", "Остатки от клиента, шт", "Остатки", "num",
        [float(stock_from.get(k, 0)) for k in day_keys], None)
    add("stock_to_client", "Остатки до клиента, шт", "Остатки", "num",
        [float(stock_to.get(k, 0)) for k in day_keys], None)
    ad_spent = {k: ad.get(k, {}).get("spent", 0.0) for k in day_keys}
    add("drr_sales_pct", "ДРР по продажам, %", "Реклама", "pct",
        [(_safe_div(ad_spent[k], sales_rub.get(k, 0.0), 100) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(sales_rub.values()), 100) or 0.0)
    add("drrz_pct", "ДРР по заказам, %", "Реклама", "pct",
        [(_safe_div(ad_spent[k], orders_rub.get(k, 0.0), 100) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(orders_rub.values()), 100) or 0.0)
    add("buyout_pct", "Процент выкупа, %", "Заказы", "pct",
        [round(buyout_by_day.get(k, buyout_avg), 2) for k in day_keys],
        round(buyout_avg, 2))
    add("ad_budget_total", "Бюджет РК, ₽ (Сводный)", "Реклама", "rub",
        [ad_spent[k] for k in day_keys])
    add("ad_budget_search", "Поиск", "Реклама", "rub",
        [ad.get(k, {}).get("search", 0.0) for k in day_keys])
    add("ad_budget_shelf", "Полки + Каталог", "Реклама", "rub",
        [ad.get(k, {}).get("shelf", 0.0) for k in day_keys])
    add("ad_budget_unified", "Единая", "Реклама", "rub",
        [ad.get(k, {}).get("unified", 0.0) for k in day_keys])
    views = {k: ad.get(k, {}).get("views", 0.0) for k in day_keys}
    clicks = {k: ad.get(k, {}).get("clicks", 0.0) for k in day_keys}
    atbs = {k: ad.get(k, {}).get("atbs", 0.0) for k in day_keys}
    ad_orders = {k: ad.get(k, {}).get("ad_orders", 0.0) for k in day_keys}
    shks = {k: ad.get(k, {}).get("shks", 0.0) for k in day_keys}
    add("ctr_pct", "CTR, % (Сводный)", "Реклама", "pct",
        [(_safe_div(clicks[k], views[k], 100) or 0.0) for k in day_keys],
        _safe_div(sum(clicks.values()), sum(views.values()), 100) or 0.0)
    add("cr_pct", "CR, % (Сводный)", "Реклама", "pct",
        [(_safe_div(ad_orders[k], clicks[k], 100) or 0.0) for k in day_keys],
        _safe_div(sum(ad_orders.values()), sum(clicks.values()), 100) or 0.0)
    add("views", "Показы, шт (Сводный)", "Реклама", "num", [views[k] for k in day_keys])
    add("clicks", "Клики, шт (Сводный)", "Реклама", "num", [clicks[k] for k in day_keys])
    add("cpo_all", "CPO (все заказы), ₽", "Реклама", "rub",
        [(_safe_div(ad_spent[k], orders_cnt.get(k, 0)) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(orders_cnt.values())) or 0.0)
    add("cpc", "CPC, ₽ (Сводный)", "Реклама", "rub",
        [(_safe_div(ad_spent[k], clicks[k]) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(clicks.values())) or 0.0)
    add("cpm", "CPM, ₽ (Сводный)", "Реклама", "rub",
        [(_safe_div(ad_spent[k], views[k], 1000) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(views.values()), 1000) or 0.0)
    add("cpo_ad", "CPO (рекламные заказы), ₽", "Реклама", "rub",
        [(_safe_div(ad_spent[k], ad_orders[k]) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(ad_orders.values())) or 0.0)
    add("cpl", "CPL (корзина), ₽", "Реклама", "rub",
        [(_safe_div(ad_spent[k], atbs[k]) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(atbs.values())) or 0.0)
    add("cps", "CPS (выкуп), ₽", "Реклама", "rub",
        [(_safe_div(ad_spent[k], shks[k]) or 0.0) for k in day_keys],
        _safe_div(sum(ad_spent.values()), sum(shks.values())) or 0.0)
    add("ad_orders", "Заказы РК, шт (Сводный)", "Реклама", "num",
        [ad_orders[k] for k in day_keys])

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "days": day_keys,
        "rows": rows,
        "notes": {
            "forecast": (
                "Прогнозные продажи = заказы дня × терминальный % выкупа (Воронка). "
                "Прибыль/маржа/ROI — по коэффициентам периода из Сводного отчёта "
                "(включая OPEX и налог)."
            ),
            "campaign_types": "Поиск=тип 6; Полки+Каталог=4/5/7/8; Единая=9.",
        },
    }
