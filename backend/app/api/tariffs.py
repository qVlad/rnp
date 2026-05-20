"""Страница «Тарифы WB» — timeline + сравнение между периодами.

Тарифы WB меняются раз в неделю (объявление за 7-14 дней). Селлеру нужно
видеть историю: «склад Краснодар — с 1 мая стоимость хранения 0.12₽/литр/день,
а до этого было 0.07». Без такой timeline планирование закупок и подбор
склада — стрельба вслепую.

Источник данных: таблицы `wb_tariff_box`, `wb_tariff_pallet`,
`wb_tariff_commission` (миграция 0040). SCD Type 2 — каждое изменение WB
добавляется как новая запись с `effective_from = today`. Sync через Celery
beat `sync.tariffs` ежедневно 08:00 MSK.

ВАЖНО: данные **не tenant-scoped** (WB тарифы одинаковы для всех селлеров) —
поэтому используется обычный `get_current_user` без `current_brands_filter`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbTariffBox, WbTariffCommission, WbTariffPallet
from app.db.session import get_db
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/tariffs", tags=["tariffs"])


# ─────────────────────────────────────────────────────────────────────────
# List endpoints — для выпадающих списков на фронте
# ─────────────────────────────────────────────────────────────────────────


@router.get("/warehouses")
async def list_warehouses(
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, list[str]]:
    """Уникальные склады из box + pallet таблиц (sorted)."""
    box = (
        await session.execute(
            select(distinct(WbTariffBox.warehouse_name)).order_by(
                WbTariffBox.warehouse_name
            )
        )
    ).scalars().all()
    pallet = (
        await session.execute(
            select(distinct(WbTariffPallet.warehouse_name)).order_by(
                WbTariffPallet.warehouse_name
            )
        )
    ).scalars().all()
    merged = sorted(set(box) | set(pallet))
    return {"items": merged}


@router.get("/subjects")
async def list_subjects(
    q: Annotated[str | None, Query(description="фильтр-подстрока")] = None,
    limit: Annotated[int, Query(le=2000)] = 1000,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """Уникальные предметы (subject_name + subject_id) из commission таблицы.

    Subject_id может быть пуст для legacy записей — отдаём как None.
    Поиск по подстроке (case-insensitive). Limit нужен потому что предметов
    WB ~10к, в UI отдавать всё бессмысленно.
    """
    stmt = (
        select(
            distinct(WbTariffCommission.subject_name).label("subject_name"),
            func.max(WbTariffCommission.subject_id).label("subject_id"),
        )
        .group_by(WbTariffCommission.subject_name)
        .order_by(WbTariffCommission.subject_name)
        .limit(limit)
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(WbTariffCommission.subject_name).like(like))
    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            {"subject_name": r.subject_name, "subject_id": r.subject_id}
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────
# Timeline endpoints — точки для линейного графика
# ─────────────────────────────────────────────────────────────────────────


def _default_from() -> date:
    """По умолчанию показываем тарифы за 180 дней — две квартальные смены."""
    return date.today() - timedelta(days=180)


def _serialize_box(row: WbTariffBox) -> dict[str, Any]:
    return {
        "effective_from": row.effective_from.isoformat(),
        "warehouse_name": row.warehouse_name,
        "delivery_base": float(row.delivery_base) if row.delivery_base is not None else None,
        "delivery_liter": float(row.delivery_liter) if row.delivery_liter is not None else None,
        "delivery_expr": float(row.delivery_expr) if row.delivery_expr is not None else None,
        "storage_base": float(row.storage_base) if row.storage_base is not None else None,
        "storage_liter": float(row.storage_liter) if row.storage_liter is not None else None,
        "dt_next": row.dt_next.isoformat() if row.dt_next else None,
    }


def _serialize_pallet(row: WbTariffPallet) -> dict[str, Any]:
    d = _serialize_box(row)  # one extra field
    d["storage_expr"] = (
        float(row.storage_expr) if row.storage_expr is not None else None
    )
    return d


def _serialize_commission(row: WbTariffCommission) -> dict[str, Any]:
    return {
        "effective_from": row.effective_from.isoformat(),
        "subject_name": row.subject_name,
        "subject_id": row.subject_id,
        "commission_fbo": (
            float(row.commission_fbo) if row.commission_fbo is not None else None
        ),
        "commission_fbs": (
            float(row.commission_fbs) if row.commission_fbs is not None else None
        ),
        "commission_express": (
            float(row.commission_express)
            if row.commission_express is not None
            else None
        ),
        "paid_storage_kgvp": (
            float(row.paid_storage_kgvp)
            if row.paid_storage_kgvp is not None
            else None
        ),
        "return_cost": (
            float(row.return_cost) if row.return_cost is not None else None
        ),
    }


@router.get("/timeline/box")
async def box_timeline(
    warehouse: Annotated[str, Query(min_length=1, max_length=255)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Timeline тарифа FBO «короб» по конкретному складу.

    Возвращаем ВСЕ записи в диапазоне + одну запись «до from» (для baseline:
    UI должен знать что было ДО начала периода, чтобы корректно показать
    первый сегмент чарта).
    """
    if from_ is None:
        from_ = _default_from()
    if to is None:
        to = date.today() + timedelta(days=30)
    if from_ > to:
        raise HTTPException(400, "from > to")

    # Baseline — последняя запись СТРОГО до from
    baseline_stmt = (
        select(WbTariffBox)
        .where(
            WbTariffBox.warehouse_name == warehouse,
            WbTariffBox.effective_from < from_,
        )
        .order_by(WbTariffBox.effective_from.desc())
        .limit(1)
    )
    baseline = (await session.execute(baseline_stmt)).scalar_one_or_none()

    # Записи в диапазоне
    stmt = (
        select(WbTariffBox)
        .where(
            WbTariffBox.warehouse_name == warehouse,
            WbTariffBox.effective_from >= from_,
            WbTariffBox.effective_from <= to,
        )
        .order_by(asc(WbTariffBox.effective_from))
    )
    rows = (await session.execute(stmt)).scalars().all()

    items = []
    if baseline is not None:
        items.append({**_serialize_box(baseline), "is_baseline": True})
    items.extend([{**_serialize_box(r), "is_baseline": False} for r in rows])

    return {"items": items, "from": from_.isoformat(), "to": to.isoformat()}


@router.get("/timeline/pallet")
async def pallet_timeline(
    warehouse: Annotated[str, Query(min_length=1, max_length=255)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Timeline тарифа FBO «монопаллет» (формат идентичен box + storage_expr)."""
    if from_ is None:
        from_ = _default_from()
    if to is None:
        to = date.today() + timedelta(days=30)
    if from_ > to:
        raise HTTPException(400, "from > to")

    baseline = (
        await session.execute(
            select(WbTariffPallet)
            .where(
                WbTariffPallet.warehouse_name == warehouse,
                WbTariffPallet.effective_from < from_,
            )
            .order_by(WbTariffPallet.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    rows = (
        await session.execute(
            select(WbTariffPallet)
            .where(
                WbTariffPallet.warehouse_name == warehouse,
                WbTariffPallet.effective_from >= from_,
                WbTariffPallet.effective_from <= to,
            )
            .order_by(asc(WbTariffPallet.effective_from))
        )
    ).scalars().all()

    items = []
    if baseline is not None:
        items.append({**_serialize_pallet(baseline), "is_baseline": True})
    items.extend([{**_serialize_pallet(r), "is_baseline": False} for r in rows])

    return {"items": items, "from": from_.isoformat(), "to": to.isoformat()}


@router.get("/timeline/commission")
async def commission_timeline(
    subject: Annotated[str, Query(min_length=1, max_length=255)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Timeline комиссий WB по предмету (subject_name)."""
    if from_ is None:
        from_ = _default_from()
    if to is None:
        to = date.today() + timedelta(days=30)
    if from_ > to:
        raise HTTPException(400, "from > to")

    baseline = (
        await session.execute(
            select(WbTariffCommission)
            .where(
                WbTariffCommission.subject_name == subject,
                WbTariffCommission.effective_from < from_,
            )
            .order_by(WbTariffCommission.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    rows = (
        await session.execute(
            select(WbTariffCommission)
            .where(
                WbTariffCommission.subject_name == subject,
                WbTariffCommission.effective_from >= from_,
                WbTariffCommission.effective_from <= to,
            )
            .order_by(asc(WbTariffCommission.effective_from))
        )
    ).scalars().all()

    items = []
    if baseline is not None:
        items.append({**_serialize_commission(baseline), "is_baseline": True})
    items.extend(
        [{**_serialize_commission(r), "is_baseline": False} for r in rows]
    )

    return {"items": items, "from": from_.isoformat(), "to": to.isoformat()}


# ─────────────────────────────────────────────────────────────────────────
# Latest snapshot — что действует сейчас (для дашборда / summary)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/current")
async def current_tariffs(
    kind: Annotated[Literal["box", "pallet"], Query()] = "box",
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Действующий тариф по каждому складу (последняя запись со
    `effective_from <= today`). Удобно для overview-таблицы «все склады
    на одном экране»."""
    today = date.today()
    model = WbTariffBox if kind == "box" else WbTariffPallet
    serializer = _serialize_box if kind == "box" else _serialize_pallet

    # Подзапрос: latest effective_from по каждому складу
    subq = (
        select(
            model.warehouse_name,
            func.max(model.effective_from).label("max_eff"),
        )
        .where(model.effective_from <= today)
        .group_by(model.warehouse_name)
        .subquery()
    )

    stmt = (
        select(model)
        .join(
            subq,
            (model.warehouse_name == subq.c.warehouse_name)
            & (model.effective_from == subq.c.max_eff),
        )
        .order_by(model.warehouse_name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [serializer(r) for r in rows], "kind": kind, "as_of": today.isoformat()}
