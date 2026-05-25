"""TASK-LEAD-055 — Breakdown popup для KPI Dashboard.

При клике на KPI (logistics_wb / storage_wb / commission_wb / deduction / penalty)
возвращаем top-N SKU с разбивкой какой именно товар сколько потребляет.

Это даёт ответ «куда уходят 200к на логистику?» — «вот эти 5 SKU составляют 60%».

Используем существующие данные `wb_report_detail` + `period_aggregates` для
консистентной фильтрации (sale_dt + supplier_oper_name=Продажа/Возврат).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbReportDetail
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
    sale_dt_filter,
)
from app.services.periods import Period

BreakdownMetric = Literal[
    "logistics_wb",
    "storage_wb",
    "commission_wb",
    "deduction",
    "penalty",
]


@dataclass(frozen=True)
class BreakdownRow:
    nm_id: int
    vendor_code: str | None
    subject: str | None
    brand: str | None
    value: Decimal
    pct_of_total: float


@dataclass(frozen=True)
class BreakdownResult:
    metric: BreakdownMetric
    period_from: str
    period_to: str
    total: Decimal
    items: list[BreakdownRow]
    truncated: bool  # True если есть SKU за пределами top-N
    total_items: int  # сколько всего SKU попало в выборку (top-N + остальные)
    truncated_sum: Decimal  # сумма value у SKU за пределами top-N (residual)


METRIC_FIELD_MAP: dict[BreakdownMetric, str] = {
    "logistics_wb": "delivery_rub",
    "storage_wb": "storage_fee",
    "commission_wb": "commission_rub",  # computed below — retail × commission_percent / 100
    "deduction": "deduction",
    "penalty": "penalty",
}


METRIC_LABELS: dict[BreakdownMetric, str] = {
    "logistics_wb": "Логистика WB",
    "storage_wb": "Хранение WB",
    "commission_wb": "Комиссия WB",
    "deduction": "Удержания",
    "penalty": "Штрафы",
}


async def compute_kpi_breakdown(
    session: AsyncSession,
    period: Period,
    metric: BreakdownMetric,
    brands: set[str] | None,
    limit: int = 10,
) -> BreakdownResult:
    """Top-N SKU breakdown за период для заданной KPI-метрики.

    Для большинства метрик — просто `SUM(field) GROUP BY nm_id ORDER BY sum DESC`.

    Для `commission_wb` используется **каноничная формула Dashboard KPI**
    (см. `metrics.py:_final_finance_aggregate`):
        commission = Σ(retail − ppvz_for_pay − acquiring_fee) для Продаж
                   − Σ(retail − ppvz_for_pay − acquiring_fee) для Возвратов.
    Не «retail × commission_percent» — `commission_percent` в WB-данных
    пустой для Base-token (см. CLAUDE.md «Подводные камни» п.14), а формула
    через ppvz матчит WB-кабинет 1:1 и совпадает с тем, что Dashboard
    показывает в `commission_wb` KPI (BUG-DEV-013).

    Период-фильтр — каноничный `sale_dt_filter()` (semi-open, см.
    `period_aggregates.py`). Раньше был ручной inclusive `<= time.max`,
    который захватывал записи в полночь следующего дня → расхождение с
    Dashboard на границах суток (BUG-DEV-012).
    """
    if metric == "commission_wb":
        # Каноничная формула Dashboard: (retail − ppvz − acquiring) для Продаж − Возвратов.
        # Совпадает с _final_finance_aggregate (commission label) — Σ breakdown = KPI.
        commission_expr = (
            REVENUE_FIELD
            - WbReportDetail.ppvz_for_pay
            - func.coalesce(WbReportDetail.acquiring_fee, 0)
        )
        sale_expr = (
            func.sum(case((OP_SALE, commission_expr), else_=0))
            - func.sum(case((OP_RETURN, commission_expr), else_=0))
        ).label("value")
    else:
        field = getattr(WbReportDetail, METRIC_FIELD_MAP[metric])
        # Для delivery_rub / storage_fee / deduction / penalty — суммируем sum'ой
        # (для возвратов значения уже обычно отрицательные в исходных данных WB).
        sale_expr = func.sum(field).label("value")

    stmt = (
        select(
            WbReportDetail.nm_id,
            sale_expr,
            Product.vendor_code,
            Product.subject_name,
            Product.brand,
        )
        .outerjoin(Product, Product.nm_id == WbReportDetail.nm_id)
        .where(*sale_dt_filter(period.start, period.end))
        .group_by(
            WbReportDetail.nm_id,
            Product.vendor_code,
            Product.subject_name,
            Product.brand,
        )
        .order_by(sale_expr.desc())
    )

    if brands is not None:
        # Manager scope — фильтр по брендам через product subquery
        # (TenantScopedMixin event listener уже применит tenant_id filter)
        if not brands:
            return BreakdownResult(
                metric=metric,
                period_from=period.start.isoformat(),
                period_to=period.end.isoformat(),
                total=Decimal("0"),
                items=[],
                truncated=False,
                total_items=0,
                truncated_sum=Decimal("0"),
            )
        stmt = stmt.where(Product.brand.in_(brands))

    # Сначала считаем total за период (без limit)
    rows = (await session.execute(stmt)).all()

    total = sum((Decimal(str(r.value or 0)) for r in rows), Decimal("0"))
    truncated = len(rows) > limit
    total_items = len(rows)
    truncated_sum = sum(
        (Decimal(str(r.value or 0)) for r in rows[limit:]), Decimal("0")
    )

    items: list[BreakdownRow] = []
    for r in rows[:limit]:
        value = Decimal(str(r.value or 0))
        pct = float(value / total * 100) if total else 0.0
        items.append(
            BreakdownRow(
                nm_id=r.nm_id,
                vendor_code=r.vendor_code,
                subject=r.subject_name,
                brand=r.brand,
                value=value,
                pct_of_total=pct,
            )
        )

    return BreakdownResult(
        metric=metric,
        period_from=period.start.isoformat(),
        period_to=period.end.isoformat(),
        total=total,
        items=items,
        truncated=truncated,
        total_items=total_items,
        truncated_sum=truncated_sum,
    )
