"""OPEX many-to-many распределение — DTO, валидация, авто-распределение
(TASK-LEAD-030, миграция 0055).

После миграции 0055 каждый `OpexEntry` имеет ≥1 `OpexEntryAllocation`. По
умолчанию (backfill / новый entry без явного распределения) — одна
`tenant`-scope allocation с `weight=1.0` («вся сумма принадлежит компании,
не распределено по брендам»).

Два режима использования OPEX в P&L:

  - `company_scope` (director / head, без brands-фильтра): читает
    `SUM(amount)` напрямую из `opex_entries` без JOIN allocations.
    Это **гарантирует Δ=0₽** в reconciliation/P&L total numbers —
    company видит полную сумму расхода независимо от распределения.

  - `manager_scope` (с brands-фильтром): JOIN'ит allocations и применяет
    `amount × effective_weight`, где `effective_weight` =
    Σ по allocations которые попадают в user_brands:
      * `scope_type='brand'`  → weight, если scope_value ∈ user_brands; иначе 0
      * `scope_type='nm'`     → weight, если Product[scope_value].brand ∈ brands
      * `scope_type='group'`  → weight × (доля nm в группе с brand ∈ brands)
      * `scope_type='tenant'` → 0 (для manager не показываем «нераспределённое»)

  Сумма manager-scope view'ов брендов может быть меньше company-scope (если
  Σweights < 1.0 — часть residual осталась «нераспределено»). Это
  задокументированное поведение.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    OpexEntryAllocation,
    Product,
    ProductGroupAssignment,
    WbReportDetail,
)
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
    sale_dt_filter,
)

# Точность хранения = NUMERIC(10,4). Эпсилон округления Σweights.
WEIGHT_EPSILON = Decimal("0.0001")

ScopeType = Literal["tenant", "brand", "group", "nm"]
SCOPE_TYPES: tuple[str, ...] = ("tenant", "brand", "group", "nm")
NON_TENANT_SCOPE_TYPES: tuple[str, ...] = ("brand", "group", "nm")


@dataclass(frozen=True)
class Allocation:
    """Один scope с весом для конкретного OpexEntry."""

    scope_type: ScopeType
    scope_value: str | None  # None только для scope_type='tenant'
    weight: Decimal


class AllocationValidationError(ValueError):
    """Σ weights > 1.0+ε или некорректные поля."""


def validate_allocations(allocations: list[Allocation]) -> None:
    """Проверка перед сохранением. Бросает AllocationValidationError.

    Правила:
      * scope_type ∈ SCOPE_TYPES
      * weight ∈ [0, 1]
      * для scope_type='tenant'      → scope_value is None
      * для scope_type ∈ {brand,group,nm} → scope_value not None and not empty
      * Σweight ≤ 1.0 + ε
      * не более одной allocation с одинаковым (scope_type, scope_value)
    """
    seen: set[tuple[str, str | None]] = set()
    total = Decimal("0")
    for a in allocations:
        if a.scope_type not in SCOPE_TYPES:
            raise AllocationValidationError(
                f"invalid scope_type: {a.scope_type!r} (allowed: {SCOPE_TYPES})"
            )
        if a.weight < 0 or a.weight > 1:
            raise AllocationValidationError(
                f"weight {a.weight} вне [0, 1] для scope ({a.scope_type}, {a.scope_value})"
            )
        if a.scope_type == "tenant":
            if a.scope_value is not None:
                raise AllocationValidationError(
                    "scope_type='tenant' требует scope_value=None"
                )
        else:
            if a.scope_value is None or a.scope_value == "":
                raise AllocationValidationError(
                    f"scope_type={a.scope_type!r} требует непустого scope_value"
                )
        key = (a.scope_type, a.scope_value)
        if key in seen:
            raise AllocationValidationError(
                f"duplicate allocation для scope ({a.scope_type}, {a.scope_value})"
            )
        seen.add(key)
        total += a.weight
    if total > Decimal("1") + WEIGHT_EPSILON:
        raise AllocationValidationError(
            f"Σweights = {total} > 1.0 (допустимо ≤ 1.0 + {WEIGHT_EPSILON})"
        )


async def manager_scope_effective_weights(
    user_brands: set[str], session: AsyncSession
) -> dict[int, Decimal]:
    """Для manager-view: вернуть `dict[opex_id → total_effective_weight]`.

    `tenant`-allocations исключены (их не видит manager — это residual
    company-only). Группы резолвятся в Python: для каждой группы
    `effective_share = (nm с brand ∈ user_brands) / (всего nm в группе)`,
    финальный вес allocation = `weight × effective_share`.

    Если для какого-то opex_id ни одна allocation не попадает в user_brands —
    его не будет в результате (отфильтруется в SQL через `.in_(eff_weights)`).

    Tenant-фильтрация делается автоматически через
    `tenant_context.set_tenant` (event listener в SQLAlchemy session).
    """
    if not user_brands:
        return {}

    # 1) Все non-tenant allocations.
    rows = (
        await session.execute(
            select(
                OpexEntryAllocation.opex_id,
                OpexEntryAllocation.scope_type,
                OpexEntryAllocation.scope_value,
                OpexEntryAllocation.weight,
            ).where(OpexEntryAllocation.scope_type.in_(NON_TENANT_SCOPE_TYPES))
        )
    ).all()
    if not rows:
        return {}

    # 2) Резолв nm→brand для scope_type='nm'.
    nm_ids: list[int] = []
    for r in rows:
        if r.scope_type == "nm" and r.scope_value:
            try:
                nm_ids.append(int(r.scope_value))
            except ValueError:
                continue
    nm_brand: dict[int, str | None] = {}
    if nm_ids:
        nm_rows = (
            await session.execute(
                select(Product.nm_id, Product.brand).where(
                    Product.nm_id.in_(list(set(nm_ids)))
                )
            )
        ).all()
        nm_brand = {int(r.nm_id): r.brand for r in nm_rows}

    # 3) Резолв group→fraction(in_user_brands).
    group_ids: list[int] = []
    for r in rows:
        if r.scope_type == "group" and r.scope_value:
            try:
                group_ids.append(int(r.scope_value))
            except ValueError:
                continue
    group_fraction: dict[int, Decimal] = {}
    if group_ids:
        # Одна SQL-агрегация: COUNT в брендах / COUNT всего по группе.
        brand_in = Product.brand.in_(list(user_brands))
        g_rows = (
            await session.execute(
                select(
                    ProductGroupAssignment.group_id.label("gid"),
                    func.count().label("total"),
                    func.sum(case((brand_in, 1), else_=0)).label("in_brands"),
                )
                .join(Product, Product.nm_id == ProductGroupAssignment.nm_id)
                .where(ProductGroupAssignment.group_id.in_(list(set(group_ids))))
                .group_by(ProductGroupAssignment.group_id)
            )
        ).all()
        for r in g_rows:
            total = int(r.total or 0)
            in_b = int(r.in_brands or 0)
            group_fraction[int(r.gid)] = (
                Decimal(in_b) / Decimal(total) if total > 0 else Decimal(0)
            )

    # 4) Свёртка по opex_id.
    result: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in rows:
        w = Decimal(r.weight)
        sv = r.scope_value
        contrib = Decimal("0")
        if r.scope_type == "brand":
            if sv in user_brands:
                contrib = w
        elif r.scope_type == "nm":
            try:
                brand = nm_brand.get(int(sv)) if sv else None
            except ValueError:
                brand = None
            if brand and brand in user_brands:
                contrib = w
        elif r.scope_type == "group":
            try:
                gid = int(sv) if sv else None
            except ValueError:
                gid = None
            if gid is not None:
                contrib = w * group_fraction.get(gid, Decimal("0"))
        if contrib > 0:
            result[int(r.opex_id)] += contrib
    return dict(result)


async def compute_weights_preview(
    *,
    mode: Literal["equal", "revenue_share"],
    target_scopes: list[tuple[str, str]],
    period_from: date,
    period_to: date,
    session: AsyncSession,
) -> list[Allocation]:
    """Превью весов для UI. Не сохраняет в БД — возвращает список Allocation,
    который фронт показывает пользователю, тот edit'ит и сохраняет через PUT.

    `target_scopes` — список `(scope_type, scope_value)` куда распределять.
    Допустимые scope_type: 'brand' / 'group' / 'nm'. Tenant в превью не
    участвует (residual вычисляется автоматически как 1 − Σ).

    Modes:
      * 'equal'         — w = 1 / N (с rounding residual в последнем bucket'е)
      * 'revenue_share' — w_i = revenue_i / Σ revenue, период
        `[period_from, period_to]` × `sale_dt_filter` × `OP_SALE − OP_RETURN`
        с REVENUE_FIELD. Резолв scope: brand → group_by(brand);
        nm → revenue по этому nm; group → суммарная revenue группы.
    """
    if not target_scopes:
        return []

    # Валидация типов
    for st, sv in target_scopes:
        if st not in NON_TENANT_SCOPE_TYPES:
            raise AllocationValidationError(
                f"target_scopes: недопустимый scope_type {st!r}"
            )
        if not sv:
            raise AllocationValidationError(
                f"target_scopes: пустой scope_value для {st!r}"
            )

    if mode == "equal":
        n = len(target_scopes)
        # Квантование до 4 знаков. Residual rounding отправляется в последний bucket.
        base = (Decimal("1") / Decimal(n)).quantize(WEIGHT_EPSILON)
        weights = [base] * (n - 1)
        last = Decimal("1") - sum(weights, Decimal("0"))
        weights.append(last.quantize(WEIGHT_EPSILON))
        return [
            Allocation(scope_type=st, scope_value=sv, weight=w)  # type: ignore[arg-type]
            for (st, sv), w in zip(target_scopes, weights, strict=True)
        ]

    if mode == "revenue_share":
        revenues = await _revenues_for_scopes(
            target_scopes, period_from, period_to, session
        )
        total = sum(revenues.values(), Decimal("0"))
        if total <= 0:
            # В периоде нет выручки → возвращаем нули (UI скажет «нечего распределять»).
            return [
                Allocation(scope_type=st, scope_value=sv, weight=Decimal(0))  # type: ignore[arg-type]
                for st, sv in target_scopes
            ]
        # Нормализация с rounding-residual в последнем bucket'е.
        result: list[Allocation] = []
        accum = Decimal("0")
        for i, (st, sv) in enumerate(target_scopes):
            rev = revenues.get((st, sv), Decimal("0"))
            if i == len(target_scopes) - 1:
                w = (Decimal("1") - accum).quantize(WEIGHT_EPSILON)
            else:
                w = (rev / total).quantize(WEIGHT_EPSILON)
                accum += w
            if w < 0:
                w = Decimal(0)
            if w > 1:
                w = Decimal(1)
            result.append(
                Allocation(scope_type=st, scope_value=sv, weight=w)  # type: ignore[arg-type]
            )
        return result

    raise AllocationValidationError(f"unknown mode: {mode!r}")


async def _revenues_for_scopes(
    target_scopes: list[tuple[str, str]],
    period_from: date,
    period_to: date,
    session: AsyncSession,
) -> dict[tuple[str, str], Decimal]:
    """Net revenue (Продажа − Возврат) по каждому scope за период."""
    result: dict[tuple[str, str], Decimal] = {}

    net_revenue_expr = func.coalesce(
        func.sum(case((OP_SALE, REVENUE_FIELD), else_=0))
        - func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0)),
        0,
    )

    brand_targets = [sv for st, sv in target_scopes if st == "brand"]
    nm_targets = [sv for st, sv in target_scopes if st == "nm"]
    group_targets = [sv for st, sv in target_scopes if st == "group"]

    # brand → revenue (JOIN Product on nm_id)
    if brand_targets:
        rows = (
            await session.execute(
                select(Product.brand, net_revenue_expr.label("rev"))
                .join(Product, Product.nm_id == WbReportDetail.nm_id)
                .where(
                    *sale_dt_filter(period_from, period_to),
                    Product.brand.in_(brand_targets),
                )
                .group_by(Product.brand)
            )
        ).all()
        for r in rows:
            if r.brand:
                result[("brand", r.brand)] = Decimal(r.rev or 0)

    # nm → revenue (по самому nm_id)
    if nm_targets:
        try:
            nm_int = [int(v) for v in nm_targets]
        except ValueError:
            nm_int = []
        if nm_int:
            rows = (
                await session.execute(
                    select(WbReportDetail.nm_id, net_revenue_expr.label("rev"))
                    .where(
                        *sale_dt_filter(period_from, period_to),
                        WbReportDetail.nm_id.in_(nm_int),
                    )
                    .group_by(WbReportDetail.nm_id)
                )
            ).all()
            for r in rows:
                result[("nm", str(r.nm_id))] = Decimal(r.rev or 0)

    # group → revenue (JOIN ProductGroupAssignment on nm_id)
    if group_targets:
        try:
            g_int = [int(v) for v in group_targets]
        except ValueError:
            g_int = []
        if g_int:
            rows = (
                await session.execute(
                    select(
                        ProductGroupAssignment.group_id,
                        net_revenue_expr.label("rev"),
                    )
                    .join(
                        ProductGroupAssignment,
                        ProductGroupAssignment.nm_id == WbReportDetail.nm_id,
                    )
                    .where(
                        *sale_dt_filter(period_from, period_to),
                        ProductGroupAssignment.group_id.in_(g_int),
                    )
                    .group_by(ProductGroupAssignment.group_id)
                )
            ).all()
            for r in rows:
                result[("group", str(r.group_id))] = Decimal(r.rev or 0)

    # Заполнить нулями для scope'ов, по которым SQL ничего не вернул
    # (например, в периоде не было продаж по этому бренду).
    for st, sv in target_scopes:
        result.setdefault((st, sv), Decimal(0))
    return result
