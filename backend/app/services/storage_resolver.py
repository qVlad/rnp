"""Единый источник правды для «Хранение WB» по периоду.

WB присылает хранение двумя путями:
  1. **report_detail.storage_fee** — агрегатно за неделю одной строкой без
     `nm_id`. Это то, что показывает финансовый отчёт WB-кабинета (Платёж).
     Используется как fallback для свежих периодов, когда paid_storage ещё
     не пришёл, и для исторических периодов (>30 дней назад) без backfill.
  2. **paid_storage** (`/api/v1/paid_storage`) — суточные строки с привязкой
     к `nm_id`, `chrt_id`, `warehouse`. Это основной источник для unit-
     экономики и любых per-SKU отчётов. Синхронизируется ежедневно.

Эта функция возвращает суммарное хранение за окно, отдавая приоритет
paid_storage когда покрытие достаточное (>50% дней периода).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbPaidStorage, WbReportDetail


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def resolve_period_storage(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    brands_subq: Any | None = None,
) -> tuple[float, str]:
    """Вернуть (storage_total, source) за период [start, end).

    `source` ∈ {'paid_storage', 'report_detail', 'mixed'} — для логов/UI.
    """
    period_days = max(1, (end.date() - start.date()).days)

    # 1. Считаем покрытие paid_storage за период.
    paid_stmt = select(
        func.coalesce(func.sum(WbPaidStorage.warehouse_price), 0).label("amount"),
        func.count(func.distinct(WbPaidStorage.date)).label("days_covered"),
    ).where(
        WbPaidStorage.date >= start.date(),
        WbPaidStorage.date < end.date(),
    )
    if brands_subq is not None:
        paid_stmt = paid_stmt.where(WbPaidStorage.nm_id.in_(brands_subq))
    paid_row = (await session.execute(paid_stmt)).one()
    paid_amount = _f(paid_row.amount)
    paid_days = int(paid_row.days_covered or 0)

    # 2. Считаем хранение из report_detail (sum(storage_fee) на rows без nm_id).
    rd_stmt = select(
        func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("amount")
    ).where(
        WbReportDetail.sale_dt >= start,
        WbReportDetail.sale_dt < end,
    )
    if brands_subq is not None:
        # Брэнд-фильтр имеет смысл только для rows с nm_id; rows-агрегаты
        # без nm_id не отфильтровываются и попадают целиком — это OK,
        # т.к. они тоже относятся ко всему складу.
        pass
    rd_amount = _f((await session.execute(rd_stmt)).scalar_one())

    # 3. Решаем какой источник использовать.
    coverage_ratio = paid_days / period_days if period_days else 0
    if paid_amount > 0 and coverage_ratio >= 0.5:
        # Хорошее покрытие — берём paid_storage как основной.
        # Если RD-storage_fee тоже есть и больше paid — это значит часть
        # дней покрыта только RD; добавим только за непокрытые дни путём
        # пропорции (грубо). На практике WB не дублирует — paid_storage
        # содержит расчётные начисления, а storage_fee — фактические
        # списания, и они синхронизируются с лагом 1-2 недели. Берём
        # paid_storage (он точнее).
        return paid_amount, "paid_storage"

    if rd_amount > 0:
        return rd_amount, "report_detail"

    return 0.0, "none"


async def resolve_period_storage_by_nm(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    brands_subq: Any | None = None,
) -> tuple[dict[int, float], str]:
    """То же что выше, но с разбивкой per nm_id (для unit_economics).

    Если paid_storage покрытие достаточное → возвращаем dict из paid_storage.
    Иначе — пустой dict (за период данных нет, fallback должен делать caller
    через пропорциональное распределение).
    """
    period_days = max(1, (end.date() - start.date()).days)

    paid_stmt = (
        select(
            WbPaidStorage.nm_id,
            func.coalesce(func.sum(WbPaidStorage.warehouse_price), 0).label("amount"),
        )
        .where(
            WbPaidStorage.date >= start.date(),
            WbPaidStorage.date < end.date(),
        )
        .group_by(WbPaidStorage.nm_id)
    )
    if brands_subq is not None:
        paid_stmt = paid_stmt.where(WbPaidStorage.nm_id.in_(brands_subq))
    paid_rows = (await session.execute(paid_stmt)).all()

    days_covered_stmt = select(
        func.count(func.distinct(WbPaidStorage.date)).label("days")
    ).where(
        WbPaidStorage.date >= start.date(),
        WbPaidStorage.date < end.date(),
    )
    if brands_subq is not None:
        days_covered_stmt = days_covered_stmt.where(WbPaidStorage.nm_id.in_(brands_subq))
    days_covered = int((await session.execute(days_covered_stmt)).scalar_one() or 0)

    if days_covered / period_days >= 0.5 and paid_rows:
        return {int(r.nm_id): _f(r.amount) for r in paid_rows}, "paid_storage"

    return {}, "report_detail"
