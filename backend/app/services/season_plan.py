"""План сезона — прогноз выручки/заказов/прибыли на 12 месяцев вперёд.

Идея 10X: декабрь готовится в августе. WB — сильно сезонный рынок (НГ +200%,
январь -40%). Селлер должен видеть в августе что нужно завезти к ноябрю.

Алгоритм (упрощённая модель — без внешних библиотек):
  1. Берём `wb_report_detail` за последние 24 месяца (или сколько есть).
  2. Группируем по календарному месяцу: revenue, orders, units.
  3. Считаем сезонный фактор:
       month_factor[m] = avg(revenue по месяцу m) / avg(revenue по всем
                          календарным месяцам, по которым есть данные)
     Если месяц встречается > 1 раза (например, январь 2025 и 2026) — берём
     среднее по экземплярам.
  4. Базовая выручка следующего года = trailing_12m_revenue / 12 — это
     «средняя месячная выручка года».
  5. Прогноз для месяца m = base × month_factor[m].
  6. Применяем линейный тренд (если есть рост year-over-year).

Возвращаем 12 месяцев вперёд + 12 месяцев назад (для контекста).
Дополнительно: GMROI оценочный, оборачиваемость, уровень остатков.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cogs, Product, WbReportDetail
from app.services.period_aggregates import OP_SALE, REVENUE_FIELD


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = (
            date(cur.year + 1, 1, 1)
            if cur.month == 12
            else date(cur.year, cur.month + 1, 1)
        )


@dataclass
class MonthData:
    period: date
    revenue: float = 0.0
    units: int = 0
    cogs_total: float = 0.0


async def build_season_plan(
    session: AsyncSession,
    *,
    months_history: int = 24,
    months_forecast: int = 12,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Возвращает per-month массив (history + forecast)."""
    today_d = date.today()
    history_start = date(today_d.year, today_d.month, 1) - timedelta(
        days=months_history * 31
    )
    # Обрезаем до 1-го числа
    history_start = date(history_start.year, history_start.month, 1)

    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    # Sales по месяцам. ВАЖНО: одно и то же выражение date_trunc нужно использовать
    # в SELECT и GROUP BY (иначе Postgres думает что в SELECT есть не-aggregate).
    month_expr = func.date_trunc("month", WbReportDetail.sale_dt).label("month")
    sales_stmt = (
        select(
            month_expr,
            func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)).label("revenue"),
            func.sum(case((OP_SALE, 1), else_=0)).label("units"),
        )
        .where(WbReportDetail.sale_dt.is_not(None))
        .where(WbReportDetail.sale_dt >= datetime.combine(history_start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by(month_expr)
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    rows = (await session.execute(sales_stmt)).all()

    history: dict[date, MonthData] = {}
    for r in rows:
        # date_trunc возвращает datetime — приводим к date с дня = 1
        d = r.month
        if isinstance(d, datetime):
            d = d.date()
        d = date(d.year, d.month, 1)
        history[d] = MonthData(period=d, revenue=_f(r.revenue), units=int(r.units or 0))

    if not history:
        return {
            "history": [],
            "forecast": [],
            "totals": {"history_total_revenue": 0.0, "forecast_total_revenue": 0.0},
            "season_factors": {},
            "warning": "Нет исторических данных в wb_report_detail.",
        }

    history_sorted = sorted(history.values(), key=lambda x: x.period)

    # Сезонный фактор: для каждого месяца календаря (1..12) считаем avg revenue
    by_month_num: dict[int, list[float]] = defaultdict(list)
    for md in history_sorted:
        if md.revenue > 0:
            by_month_num[md.period.month].append(md.revenue)
    avg_by_month_num: dict[int, float] = {
        m: (sum(vals) / len(vals)) for m, vals in by_month_num.items() if vals
    }

    # Если данных нет за месяц — берём общую среднюю (нейтральный фактор = 1.0)
    overall_avg = (
        sum(avg_by_month_num.values()) / len(avg_by_month_num)
        if avg_by_month_num
        else 0.0
    )
    season_factors: dict[int, float] = {}
    for m in range(1, 13):
        if m in avg_by_month_num and overall_avg > 0:
            season_factors[m] = avg_by_month_num[m] / overall_avg
        else:
            season_factors[m] = 1.0

    # Trailing 12 месяцев — база для прогноза
    last_12 = [
        md
        for md in history_sorted
        if md.period
        > date(
            today_d.year - 1 if today_d.month <= 12 else today_d.year,
            today_d.month,
            1,
        )
    ]
    trailing_12_revenue = sum(md.revenue for md in last_12) if last_12 else sum(
        md.revenue for md in history_sorted[-12:]
    )
    base_monthly = trailing_12_revenue / max(1, min(12, len(last_12) or len(history_sorted)))

    # Year-over-year тренд: если есть полный предыдущий год + текущий, считаем delta
    yoy_growth = 0.0
    by_year: dict[int, float] = defaultdict(float)
    for md in history_sorted:
        by_year[md.period.year] += md.revenue
    years = sorted(by_year.keys())
    if len(years) >= 2:
        last_year = by_year[years[-2]]
        this_year_partial = by_year[years[-1]]
        # Грубая нормализация: если текущий год не полный — экстраполируем
        months_in_current = sum(1 for md in history_sorted if md.period.year == years[-1])
        if months_in_current > 0 and last_year > 0:
            current_year_extrap = this_year_partial / months_in_current * 12
            yoy_growth = (current_year_extrap / last_year - 1.0)
    yoy_growth = max(-0.5, min(2.0, yoy_growth))  # клампим [-50%, +200%]

    # Прогноз на 12 месяцев вперёд
    forecast_start = (
        date(today_d.year + 1, 1, 1)
        if today_d.month == 12
        else date(today_d.year, today_d.month + 1, 1)
    )
    forecast: list[dict[str, Any]] = []
    for i, m in enumerate(_month_iter(forecast_start, _add_months(forecast_start, months_forecast - 1))):
        sf = season_factors.get(m.month, 1.0)
        # Линейный тренд: yoy_growth × (i / 12) — растягиваем равномерно
        trend = 1.0 + yoy_growth * (i / 12.0)
        f_revenue = base_monthly * sf * trend
        forecast.append(
            {
                "period": m.isoformat(),
                "month": m.month,
                "year": m.year,
                "season_factor": round(sf, 3),
                "trend_factor": round(trend, 3),
                "forecast_revenue": round(f_revenue, 2),
                "forecast_units": int(
                    round(f_revenue / (base_monthly / sum(md.units for md in last_12) * 12)
                          if last_12 and sum(md.units for md in last_12) > 0 else 0)
                ) if last_12 else 0,
            }
        )

    # История в выходной формат
    history_out = [
        {
            "period": md.period.isoformat(),
            "month": md.period.month,
            "year": md.period.year,
            "revenue": round(md.revenue, 2),
            "units": md.units,
            "season_factor": round(season_factors.get(md.period.month, 1.0), 3),
        }
        for md in history_sorted
    ]

    return {
        "history": history_out,
        "forecast": forecast,
        "totals": {
            "history_total_revenue": round(sum(md.revenue for md in history_sorted), 2),
            "trailing_12_revenue": round(trailing_12_revenue, 2),
            "base_monthly": round(base_monthly, 2),
            "yoy_growth_pct": round(yoy_growth * 100, 2),
            "forecast_total_revenue": round(sum(f["forecast_revenue"] for f in forecast), 2),
        },
        "season_factors": {str(m): round(season_factors[m], 3) for m in range(1, 13)},
    }


def _add_months(d: date, n: int) -> date:
    y, m = d.year, d.month + n
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1)
