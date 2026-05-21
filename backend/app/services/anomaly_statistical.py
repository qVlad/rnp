"""Statistical outlier detection (TASK-LEAD-026).

В отличие от `anomaly.py` где пороги hardcoded (buyout_min_pct=60, drr_max=25
и т.д.), здесь — статистический детектор: считаем 28-дневное rolling
распределение KPI per-tenant, current_day vs distribution = outlier если
|z-score| > 2 ИЛИ значение вне IQR-fence (Tukey 1.5x).

Преимущество vs threshold: «сервис сам находит» без настройки. MPump
заявляет 13+ типов алертов — мы догоняем расширением правил, но
statistical-detector — это другой класс защиты (находит то что админ
не успел настроить руками).

Дизайн:
- Считаем daily aggregates за последние 35 дней (28-day window + 7-day buffer)
- Текущий день = последний полный (`date.today() - 1 day`)
- Distribution = предыдущие 28 точек (не включая current)
- z = (x - mean) / std, флаг при |z| > 2 (≈2.5% выборки в нормальном)
- IQR = Q3 - Q1, fence = [Q1 - 1.5*IQR, Q3 + 1.5*IQR], флаг при выходе

Результат — список dict'ов того же формата что у `anomaly.collect_alerts`:
`{level, code, message}` + `signature` через `alert_signature`.

Wire-in — в `anomaly.collect_alerts` после threshold-правил, перед
`_enrich_with_ack`.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbAdStatsDaily, WbOrder, WbReportDetail
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
    sale_dt_filter,
)


# Параметры детектора. AppSetting может перекрывать (см. anomaly._thresholds).
DEFAULT_Z_THRESHOLD = 2.0
DEFAULT_IQR_MULTIPLIER = 1.5
WINDOW_DAYS = 28


def _z_score(x: float, mean: float, std: float) -> float | None:
    if std <= 0:
        return None
    return (x - mean) / std


def _iqr_fence(values: list[float], multiplier: float) -> tuple[float, float] | None:
    """Возвращает (lower, upper) fence по Tukey, либо None если выборка мала."""
    n = len(values)
    if n < 8:
        return None
    sorted_v = sorted(values)
    q1_idx = max(0, n // 4 - 1)
    q3_idx = min(n - 1, (3 * n) // 4)
    q1 = sorted_v[q1_idx]
    q3 = sorted_v[q3_idx]
    iqr = q3 - q1
    if iqr <= 0:
        return None
    return (q1 - multiplier * iqr, q3 + multiplier * iqr)


def _basic_stats(values: list[float]) -> tuple[float, float]:
    """Mean + sample std (ddof=1) — стандарт для outlier-детекторов."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, math.sqrt(var)


async def detect_outliers(
    session: AsyncSession,
    brands: set[str] | None = None,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    iqr_multiplier: float = DEFAULT_IQR_MULTIPLIER,
) -> list[dict[str, Any]]:
    """Возвращает список alert-dict'ов для KPI-аномалий per-tenant.

    Считаем daily-агрегаты выручки (`revenue_net` = ppvz_for_pay по продажам
    минус по возвратам) за окно 28+1 дней. Прошлые 28 — distribution,
    последний полный день — наблюдение.

    Для расширения: добавить детекторы по drr / buyout — пока MVP только на
    revenue_net, как самой непосредственной метрике (выручка просела →
    обычно срочно).
    """
    alerts: list[dict[str, Any]] = []
    today = date.today()
    # Последний полный день — вчера (today может быть неполным).
    observation_day = today - timedelta(days=1)
    window_start = observation_day - timedelta(days=WINDOW_DAYS)

    # Один запрос: per-day revenue_net по supplier_oper_name. NULL-safe.
    # period_aggregates.sale_dt_filter даёт каноничный предикат окна.
    stmt = (
        select(
            WbReportDetail.sale_dt.label("d"),
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == OP_SALE, REVENUE_FIELD),
                    (WbReportDetail.supplier_oper_name == OP_RETURN, -REVENUE_FIELD),
                    else_=0,
                )
            ).label("rev"),
        )
        .where(sale_dt_filter(window_start, observation_day))
        .group_by(WbReportDetail.sale_dt)
        .order_by(WbReportDetail.sale_dt)
    )
    # Brand filter не применяем — agregate на tenant-level (для per-brand
    # outlier'ов нужна отдельная итерация, scope MVP — компанейский KPI).
    _ = brands  # noqa: F841 — placeholder для будущего расширения

    rows = (await session.execute(stmt)).all()
    if not rows:
        return alerts

    by_day = {r.d: float(r.rev or 0) for r in rows if r.d is not None}
    history = [by_day.get(window_start + timedelta(days=i), 0.0) for i in range(WINDOW_DAYS)]
    current = by_day.get(observation_day, 0.0)

    # Если current=0 и предыдущие тоже = пустые данные, пропускаем (ничего
    # необычного, просто WB ещё не дослал отчёт за вчера).
    if all(v == 0 for v in history) and current == 0:
        return alerts

    mean, std = _basic_stats(history)
    z = _z_score(current, mean, std)
    if z is not None and abs(z) > z_threshold:
        direction = "ниже" if z < 0 else "выше"
        level = "danger" if abs(z) > 3 else "warning"
        alerts.append(
            {
                "level": level,
                "code": "revenue_outlier_z",
                "message": (
                    f"Выручка за {observation_day.isoformat()}: "
                    f"{current:,.0f}₽ — {direction} 28-дневного среднего "
                    f"({mean:,.0f}₽) на {abs(z):.1f}σ. "
                    f"Обычно такое отклонение бывает реже чем раз в "
                    f"{int(round(20 if abs(z) < 2.5 else 100))} дней."
                ),
            }
        )

    fence = _iqr_fence(history, iqr_multiplier)
    if fence is not None:
        lo, hi = fence
        if current < lo or current > hi:
            # Только если z-детектор не сработал — избегаем дубля.
            if not (z is not None and abs(z) > z_threshold):
                direction = "ниже" if current < lo else "выше"
                threshold = lo if current < lo else hi
                alerts.append(
                    {
                        "level": "warning",
                        "code": "revenue_outlier_iqr",
                        "message": (
                            f"Выручка за {observation_day.isoformat()}: "
                            f"{current:,.0f}₽ — за пределами Tukey-fence "
                            f"({direction} {threshold:,.0f}₽). Стат. аномалия "
                            f"vs 28-дневного распределения."
                        ),
                    }
                )

    # ── DRR-детектор ────────────────────────────────────────────────────
    # DRR = ad_spent / revenue. Per-day из wb_ad_stats_daily / wb_report_detail.
    # Aномалия: DRR резко вырос (реклама сжигает выручку). Прирост важнее
    # снижения — здесь не оба хвоста, а только верхний.
    drr_alerts = await _detect_drr_outlier(
        session, window_start, observation_day, z_threshold, iqr_multiplier
    )
    alerts.extend(drr_alerts)

    # ── Buyout-детектор ─────────────────────────────────────────────────
    # Выкуп = выкуплено / заказано. Снижение — алерт; рост (>100% от outliers)
    # обычно не критичен (хорошо ведь).
    buyout_alerts = await _detect_buyout_outlier(
        session, window_start, observation_day, z_threshold, iqr_multiplier
    )
    alerts.extend(buyout_alerts)

    # ── Per-brand revenue-детектор ───────────────────────────────────────
    # Для каждого активного бренда — отдельная outlier-проверка по выручке.
    # Это позволяет ROP'у видеть «бренд X просел резко» даже если общая
    # компанейская выручка в норме (один бренд может быть = 5% от total).
    brand_alerts = await _detect_per_brand_outliers(
        session, window_start, observation_day, z_threshold, iqr_multiplier
    )
    alerts.extend(brand_alerts)

    # ── Per-brand DRR + buyout outliers ──────────────────────────────────
    # Расширение TASK-LEAD-026: те же z-score правила, но на (brand, day).
    # DRR-rise alert: один бренд начал жечь рекламу аномально много.
    # Buyout-drop alert: SKU конкретного бренда стали часто возвращать.
    brand_drr_alerts = await _detect_per_brand_drr_outliers(
        session, window_start, observation_day, z_threshold
    )
    alerts.extend(brand_drr_alerts)

    brand_buyout_alerts = await _detect_per_brand_buyout_outliers(
        session, window_start, observation_day, z_threshold
    )
    alerts.extend(brand_buyout_alerts)

    return alerts


async def _detect_drr_outlier(
    session: AsyncSession,
    window_start: date,
    observation_day: date,
    z_threshold: float,
    iqr_multiplier: float,
) -> list[dict[str, Any]]:
    """Per-day DRR = sum(ad_spent) / sum(orders_revenue) × 100.

    Источники:
      - ad_spent: WbAdStatsDaily.sum_spent
      - orders_revenue: WbOrder.total_price * (1 - discount_percent/100)
        для is_cancel=False

    Алертит ТОЛЬКО при росте DRR (z > +threshold) — снижение это хорошо.
    """
    alerts: list[dict[str, Any]] = []

    # Ad spent per day
    ad_stmt = (
        select(
            WbAdStatsDaily.stat_date.label("d"),
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
        )
        .where(
            WbAdStatsDaily.stat_date >= window_start,
            WbAdStatsDaily.stat_date <= observation_day,
        )
        .group_by(WbAdStatsDaily.stat_date)
    )
    spent_by_day = {
        r.d: float(r.spent or 0) for r in (await session.execute(ad_stmt)).all()
    }

    # Orders revenue per day (priceWithDisc proxy: total_price * (1 - disc/100))
    # order_dt — DateTime, конвертируем в date через func.date()
    order_day = func.date(WbOrder.order_dt).label("d")
    ord_stmt = (
        select(
            order_day,
            func.sum(
                WbOrder.total_price * (1 - WbOrder.discount_percent / 100.0)
            ).label("rev"),
        )
        .where(
            func.date(WbOrder.order_dt) >= window_start,
            func.date(WbOrder.order_dt) <= observation_day,
            WbOrder.is_cancel.is_(False),
        )
        .group_by(order_day)
    )
    rev_by_day = {
        r.d: float(r.rev or 0) for r in (await session.execute(ord_stmt)).all()
    }

    drr_by_day: dict[date, float] = {}
    for d in set(spent_by_day) | set(rev_by_day):
        s = spent_by_day.get(d, 0.0)
        r = rev_by_day.get(d, 0.0)
        if r > 0:
            drr_by_day[d] = (s / r) * 100

    days = sorted(drr_by_day.keys())
    if observation_day not in drr_by_day or len(days) < 14:
        return alerts  # недостаточно данных

    history = [drr_by_day[d] for d in days if d < observation_day]
    current = drr_by_day[observation_day]
    mean, std = _basic_stats(history)
    z = _z_score(current, mean, std)
    if z is not None and z > z_threshold:  # только верхний хвост
        level = "danger" if z > 3 else "warning"
        alerts.append(
            {
                "level": level,
                "code": "drr_outlier_z",
                "message": (
                    f"ДРР за {observation_day.isoformat()}: {current:.1f}% — "
                    f"выше 28-дневного среднего ({mean:.1f}%) на {z:.1f}σ. "
                    f"Реклама стала жечь выручку. Проверь /ads — конкретно "
                    f"какие кампании выросли в расходах."
                ),
            }
        )
    return alerts


async def _detect_buyout_outlier(
    session: AsyncSession,
    window_start: date,
    observation_day: date,
    z_threshold: float,
    iqr_multiplier: float,
) -> list[dict[str, Any]]:
    """Per-day buyout-rate (упрощённо): продажи / заказы × 100. Алертит
    ТОЛЬКО при падении (z < -threshold) — рост не критичен."""
    alerts: list[dict[str, Any]] = []

    # Заказы per day (order_dt — DateTime, конвертируем в date)
    order_day = func.date(WbOrder.order_dt).label("d")
    ord_stmt = (
        select(
            order_day,
            func.count(WbOrder.srid).label("orders"),
        )
        .where(
            func.date(WbOrder.order_dt) >= window_start,
            func.date(WbOrder.order_dt) <= observation_day,
            WbOrder.is_cancel.is_(False),
        )
        .group_by(order_day)
    )
    orders_by_day = {
        r.d: int(r.orders or 0) for r in (await session.execute(ord_stmt)).all()
    }

    # Продажи (выкупы) per sale_dt из wb_report_detail (final)
    sale_stmt = (
        select(
            WbReportDetail.sale_dt.label("d"),
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == OP_SALE, 1),
                    (WbReportDetail.supplier_oper_name == OP_RETURN, -1),
                    else_=0,
                )
            ).label("sales"),
        )
        .where(sale_dt_filter(window_start, observation_day))
        .group_by(WbReportDetail.sale_dt)
    )
    sales_by_day = {
        r.d: max(int(r.sales or 0), 0)
        for r in (await session.execute(sale_stmt)).all()
    }

    buyout_by_day: dict[date, float] = {}
    for d in orders_by_day:
        ord_n = orders_by_day[d]
        sale_n = sales_by_day.get(d, 0)
        if ord_n > 0:
            buyout_by_day[d] = (sale_n / ord_n) * 100

    days = sorted(buyout_by_day.keys())
    if observation_day not in buyout_by_day or len(days) < 14:
        return alerts

    history = [buyout_by_day[d] for d in days if d < observation_day]
    current = buyout_by_day[observation_day]
    mean, std = _basic_stats(history)
    z = _z_score(current, mean, std)
    if z is not None and z < -z_threshold:  # только нижний хвост
        level = "danger" if z < -3 else "warning"
        alerts.append(
            {
                "level": level,
                "code": "buyout_outlier_z",
                "message": (
                    f"Выкуп за {observation_day.isoformat()}: {current:.1f}% — "
                    f"ниже 28-дневного среднего ({mean:.1f}%) на {abs(z):.1f}σ. "
                    f"SKU стали возвращать чаще. Проверь /units → сортировка "
                    f"по выкупу возрастанию."
                ),
            }
        )
    return alerts


async def _detect_per_brand_outliers(
    session: AsyncSession,
    window_start: date,
    observation_day: date,
    z_threshold: float,
    iqr_multiplier: float,
) -> list[dict[str, Any]]:
    """Per-brand revenue outlier-детектор.

    Группируем выручку по (brand, sale_dt) за окно 28+1 дней. Для каждого
    бренда с достаточной историей (хотя бы 14 ненулевых точек) считаем
    z-score текущего дня. Если |z| > threshold → отдельный алерт с brand
    в коде/сообщении.

    Не дублирует общий revenue_outlier — там сумма по тенанту, здесь
    per-brand. Один бренд может просесть, общий total — нет.
    """
    alerts: list[dict[str, Any]] = []

    stmt = (
        select(
            Product.brand.label("brand"),
            WbReportDetail.sale_dt.label("d"),
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == OP_SALE, REVENUE_FIELD),
                    (WbReportDetail.supplier_oper_name == OP_RETURN, -REVENUE_FIELD),
                    else_=0,
                )
            ).label("rev"),
        )
        .join(Product, Product.nm_id == WbReportDetail.nm_id)
        .where(sale_dt_filter(window_start, observation_day))
        .where(Product.brand.isnot(None))
        .group_by(Product.brand, WbReportDetail.sale_dt)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return alerts

    # Группируем: brand → {date: rev}
    by_brand: dict[str, dict[date, float]] = {}
    for r in rows:
        if r.d is None or r.brand is None:
            continue
        by_brand.setdefault(str(r.brand), {})[r.d] = float(r.rev or 0)

    for brand, day_map in by_brand.items():
        # 28 точек назад + текущий день. Заполняем нулями там где нет данных.
        history = [
            day_map.get(window_start + timedelta(days=i), 0.0)
            for i in range(WINDOW_DAYS)
        ]
        current = day_map.get(observation_day, 0.0)
        # Skip brands с почти пустой историей: < 14 ненулевых дней
        if sum(1 for v in history if v > 0) < 14:
            continue
        # Skip если current=0 — обычно WB просто ещё не дослал отчёт
        if current == 0 and history[-1] == 0 and history[-2] == 0:
            continue
        mean, std = _basic_stats(history)
        z = _z_score(current, mean, std)
        if z is None or abs(z) <= z_threshold:
            continue
        direction = "ниже" if z < 0 else "выше"
        level = "danger" if abs(z) > 3 else "warning"
        alerts.append(
            {
                "level": level,
                "code": f"brand_revenue_outlier_z",  # noqa: F541
                "message": (
                    f"Бренд <b>{brand}</b> за {observation_day.isoformat()}: "
                    f"{current:,.0f}₽ — {direction} 28-дневного среднего "
                    f"({mean:,.0f}₽) на {abs(z):.1f}σ. Проверь /pnl → «По брендам»."
                ),
            }
        )

    # Не спамим — top-5 по абсолютной σ. Иначе на тенанте с 30+ брендов
    # после публичной распродажи может прийти 15 алертов сразу.
    alerts.sort(
        key=lambda a: float(a.get("message", "").split(" на ")[-1].split("σ")[0]),
        reverse=True,
    )
    return alerts[:5]


async def _detect_per_brand_drr_outliers(
    session: AsyncSession,
    window_start: date,
    observation_day: date,
    z_threshold: float,
) -> list[dict[str, Any]]:
    """Per-brand DRR outlier — алертит только при росте (z>+threshold)."""
    alerts: list[dict[str, Any]] = []

    ad_stmt = (
        select(
            Product.brand.label("brand"),
            WbAdStatsDaily.stat_date.label("d"),
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
        )
        .join(Product, Product.nm_id == WbAdStatsDaily.nm_id)
        .where(
            WbAdStatsDaily.stat_date >= window_start,
            WbAdStatsDaily.stat_date <= observation_day,
            Product.brand.isnot(None),
            WbAdStatsDaily.nm_id.isnot(None),
        )
        .group_by(Product.brand, WbAdStatsDaily.stat_date)
    )
    spent: dict[tuple[str, date], float] = {}
    for r in (await session.execute(ad_stmt)).all():
        if r.brand and r.d:
            spent[(str(r.brand), r.d)] = float(r.spent or 0)

    order_day = func.date(WbOrder.order_dt).label("d")
    ord_stmt = (
        select(
            Product.brand.label("brand"),
            order_day,
            func.sum(
                WbOrder.total_price * (1 - WbOrder.discount_percent / 100.0)
            ).label("rev"),
        )
        .join(Product, Product.nm_id == WbOrder.nm_id)
        .where(
            func.date(WbOrder.order_dt) >= window_start,
            func.date(WbOrder.order_dt) <= observation_day,
            WbOrder.is_cancel.is_(False),
            Product.brand.isnot(None),
        )
        .group_by(Product.brand, order_day)
    )
    rev: dict[tuple[str, date], float] = {}
    for r in (await session.execute(ord_stmt)).all():
        if r.brand and r.d:
            rev[(str(r.brand), r.d)] = float(r.rev or 0)

    drr_by_brand: dict[str, dict[date, float]] = {}
    for (brand, d), s in spent.items():
        r = rev.get((brand, d), 0.0)
        if r > 0:
            drr_by_brand.setdefault(brand, {})[d] = (s / r) * 100

    for brand, day_map in drr_by_brand.items():
        if observation_day not in day_map:
            continue
        days_data = [day_map[d] for d in sorted(day_map.keys()) if d < observation_day]
        if len(days_data) < 14:
            continue
        current = day_map[observation_day]
        mean, std = _basic_stats(days_data)
        z = _z_score(current, mean, std)
        if z is None or z <= z_threshold:
            continue
        level = "danger" if z > 3 else "warning"
        alerts.append({
            "level": level,
            "code": "brand_drr_outlier_z",
            "message": (
                f"ДРР бренда <b>{brand}</b> за {observation_day.isoformat()}: "
                f"{current:.1f}% — выше 28-дневного среднего ({mean:.1f}%) "
                f"на {z:.1f}σ. Реклама бренда жжёт выручку. Проверь /ads."
            ),
        })

    alerts.sort(
        key=lambda a: float(a.get("message", "").split(" на ")[-1].split("σ")[0]),
        reverse=True,
    )
    return alerts[:5]


async def _detect_per_brand_buyout_outliers(
    session: AsyncSession,
    window_start: date,
    observation_day: date,
    z_threshold: float,
) -> list[dict[str, Any]]:
    """Per-brand buyout — алертит только при падении (z<-threshold)."""
    alerts: list[dict[str, Any]] = []

    order_day = func.date(WbOrder.order_dt).label("d")
    ord_stmt = (
        select(
            Product.brand.label("brand"),
            order_day,
            func.count(WbOrder.srid).label("orders"),
        )
        .join(Product, Product.nm_id == WbOrder.nm_id)
        .where(
            func.date(WbOrder.order_dt) >= window_start,
            func.date(WbOrder.order_dt) <= observation_day,
            WbOrder.is_cancel.is_(False),
            Product.brand.isnot(None),
        )
        .group_by(Product.brand, order_day)
    )
    orders: dict[tuple[str, date], int] = {}
    for r in (await session.execute(ord_stmt)).all():
        if r.brand and r.d:
            orders[(str(r.brand), r.d)] = int(r.orders or 0)

    sale_stmt = (
        select(
            Product.brand.label("brand"),
            WbReportDetail.sale_dt.label("d"),
            func.sum(
                case(
                    (WbReportDetail.supplier_oper_name == OP_SALE, 1),
                    (WbReportDetail.supplier_oper_name == OP_RETURN, -1),
                    else_=0,
                )
            ).label("sales"),
        )
        .join(Product, Product.nm_id == WbReportDetail.nm_id)
        .where(
            sale_dt_filter(window_start, observation_day),
            Product.brand.isnot(None),
        )
        .group_by(Product.brand, WbReportDetail.sale_dt)
    )
    sales: dict[tuple[str, date], int] = {}
    for r in (await session.execute(sale_stmt)).all():
        if r.brand and r.d:
            sales[(str(r.brand), r.d)] = max(int(r.sales or 0), 0)

    buyout_by_brand: dict[str, dict[date, float]] = {}
    for (brand, d), ord_n in orders.items():
        if ord_n > 0:
            sale_n = sales.get((brand, d), 0)
            buyout_by_brand.setdefault(brand, {})[d] = (sale_n / ord_n) * 100

    for brand, day_map in buyout_by_brand.items():
        if observation_day not in day_map:
            continue
        days_data = [day_map[d] for d in sorted(day_map.keys()) if d < observation_day]
        if len(days_data) < 14:
            continue
        current = day_map[observation_day]
        mean, std = _basic_stats(days_data)
        z = _z_score(current, mean, std)
        if z is None or z >= -z_threshold:
            continue
        level = "danger" if z < -3 else "warning"
        alerts.append({
            "level": level,
            "code": "brand_buyout_outlier_z",
            "message": (
                f"Выкуп бренда <b>{brand}</b> за {observation_day.isoformat()}: "
                f"{current:.1f}% — ниже 28-дневного среднего ({mean:.1f}%) "
                f"на {abs(z):.1f}σ. SKU бренда стали возвращать чаще."
            ),
        })

    alerts.sort(
        key=lambda a: float(a.get("message", "").split(" на ")[-1].split("σ")[0]),
        reverse=True,
    )
    return alerts[:5]
