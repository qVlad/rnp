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

from app.db.models import WbReportDetail
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

    return alerts
