"""Inventory snapshot — WB-склад капитализация (TASK-LEAD-028).

Read-only сервис поверх существующих `wb_stocks_snapshot` + `cogs`.

Капитализация = Σ(qty × cost_for_date(nm_id, on_date)) на конкретную дату.
Источник qty: latest `wb_stocks_snapshot` где `snapshot_dt::date <= on_date`,
группируем по `nm_id` (берём `quantity_full` — общий остаток с учётом
in_way).
Источник cost: `Cogs` timeline (берём latest `valid_from <= on_date`),
через готовый `pnl_builder.build_cogs_lookup` + `cost_for_date`.

Никаких миграций: чисто аналитика поверх таблиц 0009/0001.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductGroup, ProductGroupAssignment, WbStockSnapshot
from app.services.pnl_builder import build_cogs_lookup, cost_for_date


Scope = Literal["brand", "group", "warehouse"]
Freq = Literal["week", "month"]


def _end_of_day(d: date) -> datetime:
    """Конец дня в UTC — для отсечки snapshot_dt <= d (включительно)."""
    return datetime.combine(d, time(23, 59, 59, 999999), tzinfo=timezone.utc)


async def _latest_qty_by_nm(
    session: AsyncSession,
    on_date: date,
    *,
    nm_filter: list[int] | None = None,
    warehouse: bool = False,
) -> list[Any]:
    """Latest snapshot per nm_id (или per nm+warehouse) на конец дня `on_date`.

    Возвращает rows с полями: nm_id, [warehouse_name], qty.
    qty — Σ quantity_full из самого свежего snapshot_dt <= on_date.

    Алгоритм: находим `max(snapshot_dt)` per nm_id (или per (nm,warehouse))
    где `snapshot_dt <= on_date`, потом join обратно и суммируем qty по этой
    точке во времени.
    """
    cutoff = _end_of_day(on_date)

    # Subquery: latest snapshot_dt per nm (или per nm+warehouse) до cutoff
    group_cols = [WbStockSnapshot.nm_id]
    if warehouse:
        group_cols.append(WbStockSnapshot.warehouse_name)

    latest_sub = (
        select(*group_cols, func.max(WbStockSnapshot.snapshot_dt).label("max_dt"))
        .where(WbStockSnapshot.snapshot_dt <= cutoff)
    )
    if nm_filter is not None:
        if not nm_filter:
            return []
        latest_sub = latest_sub.where(WbStockSnapshot.nm_id.in_(nm_filter))
    latest_sub = latest_sub.group_by(*group_cols).subquery()

    join_cond = and_(
        WbStockSnapshot.nm_id == latest_sub.c.nm_id,
        WbStockSnapshot.snapshot_dt == latest_sub.c.max_dt,
    )
    if warehouse:
        # NULL-safe сравнение warehouse_name через coalesce sentinel
        join_cond = and_(
            join_cond,
            func.coalesce(WbStockSnapshot.warehouse_name, "")
            == func.coalesce(latest_sub.c.warehouse_name, ""),
        )

    select_cols = [
        WbStockSnapshot.nm_id.label("nm_id"),
        func.sum(WbStockSnapshot.quantity_full).label("qty"),
    ]
    group_by_cols = [WbStockSnapshot.nm_id]
    if warehouse:
        select_cols.insert(1, WbStockSnapshot.warehouse_name.label("warehouse_name"))
        group_by_cols.append(WbStockSnapshot.warehouse_name)

    stmt = select(*select_cols).select_from(WbStockSnapshot).join(latest_sub, join_cond)
    if nm_filter is not None:
        if not nm_filter:
            return []
        stmt = stmt.where(WbStockSnapshot.nm_id.in_(nm_filter))
    stmt = stmt.group_by(*group_by_cols)

    rows = (await session.execute(stmt)).all()
    return rows


async def _nm_ids_for_brands(
    session: AsyncSession, brands: set[str] | None
) -> list[int] | None:
    """Список nm_id для брендов (manager). None ⇒ unrestricted."""
    if brands is None:
        return None
    if not brands:
        return []
    rows = (
        await session.execute(
            select(Product.nm_id).where(Product.brand.in_(list(brands)))
        )
    ).scalars().all()
    return [int(x) for x in rows]


async def capitalization(
    session: AsyncSession,
    tenant_id: int,
    on_date: date,
    brand_filter: set[str] | None = None,
) -> Decimal:
    """Σ(qty × cost_for_date(nm_id, on_date)) на дату `on_date`.

    `tenant_id` фактически приходит через `set_tenant`-event-listener сессии
    (передаём для явности и для будущей независимой от listener реализации).
    Все SELECT'ы автоматически фильтруются `tenant_id`.

    Возвращает Decimal в рублях (с округлением до копеек caller'ом).
    """
    nm_filter = await _nm_ids_for_brands(session, brand_filter)
    if nm_filter == []:
        return Decimal("0")

    rows = await _latest_qty_by_nm(session, on_date, nm_filter=nm_filter)
    if not rows:
        return Decimal("0")

    cogs_lookup = await build_cogs_lookup(session)
    total = Decimal("0")
    for r in rows:
        qty = int(r.qty or 0)
        if qty <= 0:
            continue
        cost = cost_for_date(cogs_lookup, int(r.nm_id), on_date)
        total += Decimal(str(qty)) * Decimal(str(cost))
    return total


async def dynamic(
    session: AsyncSession,
    tenant_id: int,
    date_from: date,
    date_to: date,
    freq: Freq = "week",
    brand_filter: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Серия точек {date, value} от `date_from` до `date_to` с шагом freq.

    freq='week' — каждое воскресенье попадает в выборку (или последний
        день периода, если он раньше).
    freq='month' — последний день каждого месяца попадает в выборку (или
        последний день периода, если он раньше).

    Реализация — простая: считаем `capitalization()` для каждой точки.
    Для типичного периода (год, freq=week) это 52 точки × один cogs_lookup
    (мы рассчитываем lookup один раз и переиспользуем).
    """
    if date_to < date_from:
        return []

    # Pre-compute nm_filter и cogs_lookup один раз
    nm_filter = await _nm_ids_for_brands(session, brand_filter)
    if nm_filter == []:
        # Нет ни одного nm_id у manager'а — пустая серия
        points = _iter_points(date_from, date_to, freq)
        return [{"date": d.isoformat(), "value": 0.0} for d in points]

    cogs_lookup = await build_cogs_lookup(session)

    points = _iter_points(date_from, date_to, freq)
    out: list[dict[str, Any]] = []
    for d in points:
        rows = await _latest_qty_by_nm(session, d, nm_filter=nm_filter)
        total = Decimal("0")
        for r in rows:
            qty = int(r.qty or 0)
            if qty <= 0:
                continue
            cost = cost_for_date(cogs_lookup, int(r.nm_id), d)
            total += Decimal(str(qty)) * Decimal(str(cost))
        out.append({"date": d.isoformat(), "value": float(total)})
    return out


def _iter_points(date_from: date, date_to: date, freq: Freq) -> list[date]:
    """Генерируем точки шага freq в интервале [date_from, date_to]."""
    pts: list[date] = []
    if freq == "week":
        # Каждое воскресенье в интервале + всегда финальная дата
        d = date_from
        # До первого воскресенья
        while d <= date_to and d.weekday() != 6:
            d += timedelta(days=1)
        while d <= date_to:
            pts.append(d)
            d += timedelta(days=7)
        if not pts or pts[-1] != date_to:
            pts.append(date_to)
    else:  # month
        # Последний день каждого месяца + финальная дата
        y, m = date_from.year, date_from.month
        while True:
            # Last day of month (y, m)
            if m == 12:
                next_first = date(y + 1, 1, 1)
            else:
                next_first = date(y, m + 1, 1)
            last_day = next_first - timedelta(days=1)
            if last_day > date_to:
                break
            if last_day >= date_from:
                pts.append(last_day)
            y, m = next_first.year, next_first.month
        if not pts or pts[-1] != date_to:
            pts.append(date_to)
    return pts


async def breakdown_by(
    session: AsyncSession,
    tenant_id: int,
    on_date: date,
    scope: Scope,
    brand_filter: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Разбивка капитализации на дату `on_date` по brand / group / warehouse.

    Возвращает list[{key, qty, value}] отсортированный по value DESC.
    scope='warehouse' пока не имеет смешения qty по разным warehouse в одном
    snapshot — берём latest per (nm, warehouse).
    """
    nm_filter = await _nm_ids_for_brands(session, brand_filter)
    if nm_filter == []:
        return []

    cogs_lookup = await build_cogs_lookup(session)

    if scope == "warehouse":
        rows = await _latest_qty_by_nm(
            session, on_date, nm_filter=nm_filter, warehouse=True
        )
        # Map nm → cost так как qty размазана по разным warehouse
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            qty = int(r.qty or 0)
            if qty <= 0:
                continue
            wh = r.warehouse_name or "—"
            cost = cost_for_date(cogs_lookup, int(r.nm_id), on_date)
            entry = agg.setdefault(wh, {"key": wh, "qty": 0, "value": 0.0})
            entry["qty"] += qty
            entry["value"] += qty * cost
        out = sorted(agg.values(), key=lambda e: e["value"], reverse=True)
        return out

    # brand / group — нужен JOIN на Product / ProductGroup
    rows = await _latest_qty_by_nm(session, on_date, nm_filter=nm_filter)
    if not rows:
        return []

    nm_ids = [int(r.nm_id) for r in rows]
    qty_by_nm = {int(r.nm_id): int(r.qty or 0) for r in rows}

    if scope == "brand":
        # nm → brand map
        brand_rows = (
            await session.execute(
                select(Product.nm_id, Product.brand).where(Product.nm_id.in_(nm_ids))
            )
        ).all()
        nm_to_key = {int(r.nm_id): (r.brand or "—") for r in brand_rows}
    else:  # group
        # nm → group(s) map (один nm может быть в нескольких группах — каждая
        # учитывается с полным qty; consciously double-count, как везде в проекте).
        group_rows = (
            await session.execute(
                select(
                    ProductGroupAssignment.nm_id,
                    ProductGroup.name,
                )
                .join(
                    ProductGroup,
                    ProductGroup.id == ProductGroupAssignment.group_id,
                )
                .where(ProductGroupAssignment.nm_id.in_(nm_ids))
            )
        ).all()
        nm_to_groups: dict[int, list[str]] = {}
        for r in group_rows:
            nm_to_groups.setdefault(int(r.nm_id), []).append(r.name)
        # nm без группы — попадает в «—»
        nm_to_key = {}
        for nm in nm_ids:
            grps = nm_to_groups.get(nm)
            if grps:
                nm_to_key[nm] = grps  # type: ignore[assignment]
            else:
                nm_to_key[nm] = ["—"]  # type: ignore[assignment]

    agg: dict[str, dict[str, Any]] = {}
    for nm, qty in qty_by_nm.items():
        if qty <= 0:
            continue
        cost = cost_for_date(cogs_lookup, nm, on_date)
        value = qty * cost
        keys = nm_to_key.get(nm, "—")
        if isinstance(keys, list):
            iter_keys = keys
        else:
            iter_keys = [keys]
        for k in iter_keys:
            entry = agg.setdefault(k, {"key": k, "qty": 0, "value": 0.0})
            entry["qty"] += qty
            entry["value"] += value

    out = sorted(agg.values(), key=lambda e: e["value"], reverse=True)
    return out
