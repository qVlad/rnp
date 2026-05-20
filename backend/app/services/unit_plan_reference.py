"""SCD Type 2 upsert-хелперы для WB-тарифов (UNIT-PLAN reference).

Тарифы WB (box / pallet / commission) — глобальный справочник без `tenant_id`,
синхронизируется ежедневной Celery beat task `sync.tariffs`.

Подход — SCD Type 2 («slowly changing dimension»):

- Сравниваем приходящую запись WB с **последней** существующей по бизнес-ключу
  (warehouse_name / subject_name) — выбор по ``effective_from DESC LIMIT 1``.
- Если значения бизнес-полей **изменились** → INSERT новой строки с
  ``effective_from = on_date``. Старая остаётся как историческая.
- Если значения не изменились → UPDATE ``fetched_at = now()`` существующей.
- Если ключ новый → INSERT первой строки.

Сравнение идёт **только** по бизнес-полям (delivery_*, storage_*, dt_next,
commission_*) — не по ``fetched_at`` (он по определению меняется каждый день).

Возврат каждой функции: ``{"inserted": N, "updated": M, "unchanged": K}`` —
для логирования в Celery task.

См. ``UNIT_PLAN.md`` §7 и модели ``WbTariffBox`` / ``WbTariffPallet`` /
``WbTariffCommission`` в ``db/models.py``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbTariffBox, WbTariffCommission, WbTariffPallet
from app.integrations.wb.tariffs import (
    BoxTariffRecord,
    CommissionRecord,
    PalletTariffRecord,
)


# ── helpers ──────────────────────────────────────────────────────────


def _eq_decimal(a: Decimal | None, b: Decimal | None) -> bool:
    """Сравнение двух Decimal | None по нормализованному значению.

    Numeric-колонки могут хранить ``"53"`` или ``"53.00"`` — для бизнес-логики
    это одно и то же. Поэтому сравниваем через ``Decimal == Decimal``, не
    через строковое представление.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return Decimal(a) == Decimal(b)
    except Exception:  # noqa: BLE001 — defensive, malformed Decimal в БД
        return False


def _eq_date(a: date | None, b: date | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a == b


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _latest_by_key(
    session: AsyncSession,
    model: Any,
    key_field: str,
    key_values: Iterable[str],
):
    """SELECT DISTINCT ON (key) ... ORDER BY key, effective_from DESC.

    Возвращает coroutine — caller сам await'ит. Возвращает ``list[Row]``,
    где Row — instance модели (latest snapshot per key).
    """
    keys = list({k for k in key_values if k})
    if not keys:
        async def _empty() -> list[Any]:
            return []
        return _empty()

    key_col = getattr(model, key_field)
    stmt = (
        select(model)
        .where(key_col.in_(keys))
        .order_by(key_col, model.effective_from.desc())
        .distinct(key_col)
    )

    async def _run() -> list[Any]:
        result = await session.execute(stmt)
        return list(result.scalars().all())

    return _run()


# ── box ──────────────────────────────────────────────────────────────


_BOX_FIELDS: tuple[str, ...] = (
    "delivery_base",
    "delivery_liter",
    "delivery_expr",
    "storage_base",
    "storage_liter",
    "dt_next",
)


def _box_unchanged(existing: WbTariffBox, rec: BoxTariffRecord) -> bool:
    return (
        _eq_decimal(existing.delivery_base, rec.delivery_base)
        and _eq_decimal(existing.delivery_liter, rec.delivery_liter)
        and _eq_decimal(existing.delivery_expr, rec.delivery_expr)
        and _eq_decimal(existing.storage_base, rec.storage_base)
        and _eq_decimal(existing.storage_liter, rec.storage_liter)
        and _eq_date(existing.dt_next, rec.dt_next)
    )


async def upsert_box_tariffs(
    session: AsyncSession,
    records: list[BoxTariffRecord],
    on_date: date,
) -> dict[str, int]:
    """SCD Type 2 upsert тарифов FBO-короб.

    See module docstring. Возвращает счётчики (inserted/updated/unchanged).
    """
    counters = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not records:
        return counters

    latest_rows = await _latest_by_key(
        session, WbTariffBox, "warehouse_name", (r.warehouse_name for r in records)
    )
    latest_by_key: dict[str, WbTariffBox] = {
        row.warehouse_name: row for row in latest_rows
    }

    now = _now_utc()
    for rec in records:
        existing = latest_by_key.get(rec.warehouse_name)
        if existing is None:
            session.add(
                WbTariffBox(
                    effective_from=on_date,
                    warehouse_name=rec.warehouse_name,
                    delivery_base=rec.delivery_base,
                    delivery_liter=rec.delivery_liter,
                    delivery_expr=rec.delivery_expr,
                    storage_base=rec.storage_base,
                    storage_liter=rec.storage_liter,
                    dt_next=rec.dt_next,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
            continue
        if _box_unchanged(existing, rec):
            existing.fetched_at = now
            counters["unchanged"] += 1
            continue
        # Бизнес-поля изменились. Защита: не создаём дубль на ту же дату —
        # если на on_date уже есть запись (например, ручной backfill утром
        # и автозапуск beat вечером), просто обновим её in place.
        if existing.effective_from == on_date:
            existing.delivery_base = rec.delivery_base
            existing.delivery_liter = rec.delivery_liter
            existing.delivery_expr = rec.delivery_expr
            existing.storage_base = rec.storage_base
            existing.storage_liter = rec.storage_liter
            existing.dt_next = rec.dt_next
            existing.fetched_at = now
            counters["updated"] += 1
        else:
            session.add(
                WbTariffBox(
                    effective_from=on_date,
                    warehouse_name=rec.warehouse_name,
                    delivery_base=rec.delivery_base,
                    delivery_liter=rec.delivery_liter,
                    delivery_expr=rec.delivery_expr,
                    storage_base=rec.storage_base,
                    storage_liter=rec.storage_liter,
                    dt_next=rec.dt_next,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
    await session.flush()
    return counters


# ── pallet ───────────────────────────────────────────────────────────


def _pallet_unchanged(existing: WbTariffPallet, rec: PalletTariffRecord) -> bool:
    return (
        _eq_decimal(existing.delivery_base, rec.delivery_base)
        and _eq_decimal(existing.delivery_liter, rec.delivery_liter)
        and _eq_decimal(existing.delivery_expr, rec.delivery_expr)
        and _eq_decimal(existing.storage_base, rec.storage_base)
        and _eq_decimal(existing.storage_liter, rec.storage_liter)
        and _eq_date(existing.dt_next, rec.dt_next)
    )


async def upsert_pallet_tariffs(
    session: AsyncSession,
    records: list[PalletTariffRecord],
    on_date: date,
) -> dict[str, int]:
    """SCD Type 2 upsert тарифов FBO-паллета. См. ``upsert_box_tariffs``."""
    counters = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not records:
        return counters

    latest_rows = await _latest_by_key(
        session, WbTariffPallet, "warehouse_name", (r.warehouse_name for r in records)
    )
    latest_by_key: dict[str, WbTariffPallet] = {
        row.warehouse_name: row for row in latest_rows
    }

    now = _now_utc()
    for rec in records:
        existing = latest_by_key.get(rec.warehouse_name)
        if existing is None:
            session.add(
                WbTariffPallet(
                    effective_from=on_date,
                    warehouse_name=rec.warehouse_name,
                    delivery_base=rec.delivery_base,
                    delivery_liter=rec.delivery_liter,
                    delivery_expr=rec.delivery_expr,
                    storage_base=rec.storage_base,
                    storage_liter=rec.storage_liter,
                    dt_next=rec.dt_next,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
            continue
        if _pallet_unchanged(existing, rec):
            existing.fetched_at = now
            counters["unchanged"] += 1
            continue
        if existing.effective_from == on_date:
            existing.delivery_base = rec.delivery_base
            existing.delivery_liter = rec.delivery_liter
            existing.delivery_expr = rec.delivery_expr
            existing.storage_base = rec.storage_base
            existing.storage_liter = rec.storage_liter
            existing.dt_next = rec.dt_next
            existing.fetched_at = now
            counters["updated"] += 1
        else:
            session.add(
                WbTariffPallet(
                    effective_from=on_date,
                    warehouse_name=rec.warehouse_name,
                    delivery_base=rec.delivery_base,
                    delivery_liter=rec.delivery_liter,
                    delivery_expr=rec.delivery_expr,
                    storage_base=rec.storage_base,
                    storage_liter=rec.storage_liter,
                    dt_next=rec.dt_next,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
    await session.flush()
    return counters


# ── commission ───────────────────────────────────────────────────────


def _commission_unchanged(
    existing: WbTariffCommission, rec: CommissionRecord
) -> bool:
    # Note: Pydantic поле `commission_fbs_express` → ORM колонка `commission_express`.
    return (
        _eq_decimal(existing.commission_fbo, rec.commission_fbo)
        and _eq_decimal(existing.commission_fbs, rec.commission_fbs)
        and _eq_decimal(existing.commission_express, rec.commission_fbs_express)
        and _eq_decimal(existing.paid_storage_kgvp, rec.paid_storage_kgvp)
        and _eq_decimal(existing.return_cost, rec.return_cost)
        and existing.subject_id == rec.subject_id
    )


async def upsert_commissions(
    session: AsyncSession,
    records: list[CommissionRecord],
    on_date: date,
) -> dict[str, int]:
    """SCD Type 2 upsert комиссий WB по предметам.

    Бизнес-ключ — ``subject_name`` (а не ``subject_id``: некоторые предметы
    приходят без id, и ``subject_name`` для них единственный стабильный
    идентификатор).
    """
    counters = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not records:
        return counters

    latest_rows = await _latest_by_key(
        session, WbTariffCommission, "subject_name", (r.subject_name for r in records)
    )
    latest_by_key: dict[str, WbTariffCommission] = {
        row.subject_name: row for row in latest_rows
    }

    now = _now_utc()
    for rec in records:
        existing = latest_by_key.get(rec.subject_name)
        if existing is None:
            session.add(
                WbTariffCommission(
                    effective_from=on_date,
                    subject_name=rec.subject_name,
                    subject_id=rec.subject_id,
                    commission_fbo=rec.commission_fbo,
                    commission_fbs=rec.commission_fbs,
                    commission_express=rec.commission_fbs_express,
                    paid_storage_kgvp=rec.paid_storage_kgvp,
                    return_cost=rec.return_cost,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
            continue
        if _commission_unchanged(existing, rec):
            existing.fetched_at = now
            counters["unchanged"] += 1
            continue
        if existing.effective_from == on_date:
            existing.subject_id = rec.subject_id
            existing.commission_fbo = rec.commission_fbo
            existing.commission_fbs = rec.commission_fbs
            existing.commission_express = rec.commission_fbs_express
            existing.paid_storage_kgvp = rec.paid_storage_kgvp
            existing.return_cost = rec.return_cost
            existing.fetched_at = now
            counters["updated"] += 1
        else:
            session.add(
                WbTariffCommission(
                    effective_from=on_date,
                    subject_name=rec.subject_name,
                    subject_id=rec.subject_id,
                    commission_fbo=rec.commission_fbo,
                    commission_fbs=rec.commission_fbs,
                    commission_express=rec.commission_fbs_express,
                    paid_storage_kgvp=rec.paid_storage_kgvp,
                    return_cost=rec.return_cost,
                    fetched_at=now,
                )
            )
            counters["inserted"] += 1
    await session.flush()
    return counters


__all__ = [
    "upsert_box_tariffs",
    "upsert_pallet_tariffs",
    "upsert_commissions",
]
