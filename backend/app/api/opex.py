"""OPEX — operational expenses outside the marketplace.

Two resources:
  - Categories  (CRUD; defaults seeded by migration 0003 with is_default=true)
  - Entries     (CRUD; the actual amount/date/comment rows)

Convention:
  - kind          "expense" | "income"
  - is_fixed      постоянные ли расходы (true для аренды/ФОТ; false для подрядчиков)
  - in_operating  if false, NOT included in operating profit (P&L), only in cash flow.
                  Use for taxes, principal repayments, dividends.

Allocations (TASK-LEAD-030, миграция 0055):
  Каждый entry может быть разнесён на N scope'ов (brand/group/nm) с весами 0..1.
  Σweights ≤ 1.0 (residual = «не распределено», остаётся только в company-scope).
  По умолчанию (новый entry без явных allocations) — создаётся одна
  `tenant`-allocation weight=1.0 («вся сумма принадлежит компании»).
  Manager P&L увидит свою долю OPEX через `pnl_builder.opex_for_period`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OpexCategory, OpexEntry, OpexEntryAllocation
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import (
    current_tenant_id,
    get_db_tenant_scoped,
    require_director,
    require_director_or_head,
)
from app.services.opex_allocations import (
    NON_TENANT_SCOPE_TYPES,
    SCOPE_TYPES,
    Allocation,
    AllocationValidationError,
    compute_weights_preview,
    validate_allocations,
)

_ENTRY_FIELDS = ["id", "entry_date", "category_id", "amount", "contractor", "comment"]
_CAT_FIELDS = ["id", "name", "kind", "is_fixed", "in_operating", "cf_section", "is_default"]

router = APIRouter(
    prefix="/api/opex",
    tags=["opex"],
    dependencies=[Depends(require_director_or_head)],
)


@router.post("/sync-ts", dependencies=[Depends(require_director)])
async def sync_ts_opex_endpoint(
    month: str | None = Query(default=None, description="YYYY-MM (иначе from+to)"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """TASK-DEV-077: синк OPEX из TrueStats (методология TS — полные операционные
    расходы с распределением, доля нашего кабинета). Помесячно, идемпотентно.
    Конфиг — AppSetting `ts_auth_token` + `ts_account_id`."""
    from app.services.opex_ts_sync import month_bounds, sync_ts_opex

    if month:
        try:
            y, m = int(month[:4]), int(month[5:7])
            date_from, date_to = month_bounds(y, m)
        except (ValueError, IndexError):
            raise HTTPException(400, "month должен быть YYYY-MM")
    if not (date_from and date_to):
        raise HTTPException(400, "Укажите month=YYYY-MM или from+to")
    res = await sync_ts_opex(session, date_from=date_from, date_to=date_to)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    await session.commit()
    return res


class OpexCategoryIn(BaseModel):
    name: str
    kind: Literal["expense", "income"] = "expense"
    is_fixed: bool = True
    in_operating: bool = True
    cf_section: Literal["operating", "investing", "financing"] = "operating"


class AllocationIn(BaseModel):
    scope_type: Literal["tenant", "brand", "group", "nm"]
    scope_value: str | None = None
    weight: float = Field(ge=0, le=1)


class OpexEntryIn(BaseModel):
    entry_date: date
    category_id: int
    amount: float
    contractor: str | None = None
    comment: str | None = None
    # Если None → backend создаст одну tenant-allocation weight=1.0.
    # Если [] → пустое распределение (residual=100%, company-scope видит всё,
    # manager не видит ничего).
    # Если [items] → явное распределение; Σweights должно быть ≤ 1.0+ε.
    allocations: list[AllocationIn] | None = None


def _cat_row(c: OpexCategory) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "is_fixed": c.is_fixed,
        "in_operating": c.in_operating,
        "cf_section": c.cf_section,
        "is_default": c.is_default,
    }


def _alloc_row(a: OpexEntryAllocation) -> dict[str, Any]:
    return {
        "scope_type": a.scope_type,
        "scope_value": a.scope_value,
        "weight": float(a.weight),
    }


def _entry_row(e: OpexEntry) -> dict[str, Any]:
    allocations = sorted(
        e.allocations or [],
        key=lambda a: (a.scope_type, a.scope_value or ""),
    )
    return {
        "id": e.id,
        "entry_date": e.entry_date.isoformat(),
        "category_id": e.category_id,
        "category_name": e.category.name if e.category else None,
        "category_kind": e.category.kind if e.category else None,
        "category_in_operating": e.category.in_operating if e.category else None,
        "category_cf_section": e.category.cf_section if e.category else None,
        "amount": float(e.amount),
        "contractor": e.contractor,
        "comment": e.comment,
        "allocations": [_alloc_row(a) for a in allocations],
    }


def _allocations_snapshot(allocs: list[OpexEntryAllocation]) -> list[dict[str, Any]]:
    """Сериализация allocations для audit_log."""
    return sorted(
        [_alloc_row(a) for a in (allocs or [])],
        key=lambda x: (x["scope_type"], x["scope_value"] or ""),
    )


def _coerce_allocations(
    raw: list[AllocationIn] | None,
) -> list[Allocation]:
    """Pydantic → внутренний Allocation DTO. None → дефолтный `tenant` w=1.0."""
    if raw is None:
        return [Allocation(scope_type="tenant", scope_value=None, weight=Decimal("1"))]
    result: list[Allocation] = []
    for item in raw:
        sv = item.scope_value
        if item.scope_type != "tenant" and (sv is None or sv == ""):
            raise AllocationValidationError(
                f"scope_type={item.scope_type!r} требует непустого scope_value"
            )
        if item.scope_type == "tenant":
            sv = None
        result.append(
            Allocation(
                scope_type=item.scope_type,  # type: ignore[arg-type]
                scope_value=sv,
                weight=Decimal(str(item.weight)),
            )
        )
    return result


async def _replace_allocations(
    session: AsyncSession,
    opex_id: int,
    tenant_id: int,
    allocations: list[Allocation],
) -> list[OpexEntryAllocation]:
    """Replace-all семантика: удалить все существующие, вставить новые.
    Вызывается под одной транзакцией (commit делает caller)."""
    await session.execute(
        delete(OpexEntryAllocation).where(OpexEntryAllocation.opex_id == opex_id)
    )
    new_rows = [
        OpexEntryAllocation(
            tenant_id=tenant_id,
            opex_id=opex_id,
            scope_type=a.scope_type,
            scope_value=a.scope_value,
            weight=a.weight,
        )
        for a in allocations
    ]
    session.add_all(new_rows)
    await session.flush()
    return new_rows


# -------- categories --------


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    stmt = select(OpexCategory).order_by(
        OpexCategory.kind.desc(),  # expense first
        OpexCategory.is_fixed.desc(),
        OpexCategory.name,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_cat_row(r) for r in rows]}


@router.post("/categories", dependencies=[Depends(require_director)])
async def create_category(
    payload: OpexCategoryIn, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, Any]:
    existing = (
        await session.execute(select(OpexCategory).where(OpexCategory.name == payload.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"category {payload.name!r} already exists")
    obj = OpexCategory(**payload.model_dump(), is_default=False)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _cat_row(obj)


@router.put("/categories/{cat_id}", dependencies=[Depends(require_director)])
async def update_category(
    cat_id: int, payload: OpexCategoryIn, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, Any]:
    obj = await session.get(OpexCategory, cat_id)
    if not obj:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await session.commit()
    await session.refresh(obj)
    return _cat_row(obj)


@router.delete("/categories/{cat_id}", dependencies=[Depends(require_director)])
async def delete_category(cat_id: int, session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, str]:
    obj = await session.get(OpexCategory, cat_id)
    if not obj:
        raise HTTPException(404, "not found")
    if obj.is_default:
        raise HTTPException(400, "cannot delete default category — clear entries instead")
    used = (
        await session.execute(select(OpexEntry).where(OpexEntry.category_id == cat_id).limit(1))
    ).scalar_one_or_none()
    if used:
        raise HTTPException(400, "category is used by entries — delete them first")
    await session.delete(obj)
    await session.commit()
    return {"status": "deleted"}


# -------- entries --------


@router.get("/entries")
async def list_entries(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    category_id: Annotated[int | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(OpexEntry)
        .options(
            selectinload(OpexEntry.category),
            selectinload(OpexEntry.allocations),
        )
        .order_by(OpexEntry.entry_date.desc(), OpexEntry.id.desc())
    )
    if date_from:
        stmt = stmt.where(OpexEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(OpexEntry.entry_date <= date_to)
    if category_id:
        stmt = stmt.where(OpexEntry.category_id == category_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_entry_row(r) for r in rows]}


@router.post("/entries")
async def create_entry(
    payload: OpexEntryIn,
    request: Request,
    tenant_id: Annotated[int, Depends(current_tenant_id)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    cat = await session.get(OpexCategory, payload.category_id)
    if not cat:
        raise HTTPException(400, "category does not exist")

    try:
        allocs = _coerce_allocations(payload.allocations)
        validate_allocations(allocs)
    except AllocationValidationError as ex:
        raise HTTPException(400, str(ex))

    obj = OpexEntry(
        entry_date=payload.entry_date,
        category_id=payload.category_id,
        amount=payload.amount,
        contractor=payload.contractor,
        comment=payload.comment,
    )
    session.add(obj)
    await session.flush()
    new_allocs = await _replace_allocations(session, obj.id, tenant_id, allocs)

    after = snapshot(obj, _ENTRY_FIELDS)
    after["allocations"] = _allocations_snapshot(new_allocs)
    await audit_log(
        session,
        "opex_entries",
        "create",
        entity_id=str(obj.id),
        after=after,
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj, attribute_names=["category", "allocations"])
    return _entry_row(obj)


@router.put("/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    payload: OpexEntryIn,
    request: Request,
    tenant_id: Annotated[int, Depends(current_tenant_id)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    obj = (
        await session.execute(
            select(OpexEntry)
            .where(OpexEntry.id == entry_id)
            .options(selectinload(OpexEntry.allocations))
        )
    ).scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "not found")
    cat = await session.get(OpexCategory, payload.category_id)
    if not cat:
        raise HTTPException(400, "category does not exist")

    try:
        allocs = _coerce_allocations(payload.allocations)
        validate_allocations(allocs)
    except AllocationValidationError as ex:
        raise HTTPException(400, str(ex))

    before = snapshot(obj, _ENTRY_FIELDS)
    before["allocations"] = _allocations_snapshot(list(obj.allocations or []))

    obj.entry_date = payload.entry_date
    obj.category_id = payload.category_id
    obj.amount = payload.amount
    obj.contractor = payload.contractor
    obj.comment = payload.comment
    new_allocs = await _replace_allocations(session, obj.id, tenant_id, allocs)

    after = snapshot(obj, _ENTRY_FIELDS)
    after["allocations"] = _allocations_snapshot(new_allocs)
    await audit_log(
        session,
        "opex_entries",
        "update",
        entity_id=str(obj.id),
        before=before,
        after=after,
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj, attribute_names=["category", "allocations"])
    return _entry_row(obj)


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    from sqlalchemy.orm import selectinload

    obj = (
        await session.execute(
            select(OpexEntry)
            .where(OpexEntry.id == entry_id)
            .options(selectinload(OpexEntry.allocations))
        )
    ).scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _ENTRY_FIELDS)
    before["allocations"] = _allocations_snapshot(list(obj.allocations or []))
    await session.delete(obj)  # CASCADE удалит allocations через FK
    await audit_log(
        session,
        "opex_entries",
        "delete",
        entity_id=str(entry_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}


# -------- allocations preview --------


class AllocationsPreviewIn(BaseModel):
    mode: Literal["equal", "revenue_share"]
    target_scopes: list[AllocationIn]
    # Период для revenue_share. Если None → последние 30 дней.
    period_from: date | None = None
    period_to: date | None = None


@router.post("/entries/allocations/preview")
async def allocations_preview(
    payload: Annotated[AllocationsPreviewIn, Body()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Не сохраняет ничего — возвращает list[Allocation] для UI.

    `target_scopes` — куда распределять (brand/group/nm; tenant в превью
    не участвует, residual вычисляется автоматически как 1 − Σ).
    """
    from datetime import timedelta

    period_to = payload.period_to or date.today()
    period_from = payload.period_from or (period_to - timedelta(days=30))

    targets: list[tuple[str, str]] = []
    for t in payload.target_scopes:
        if t.scope_type not in NON_TENANT_SCOPE_TYPES:
            raise HTTPException(
                400,
                f"target_scopes: scope_type={t.scope_type!r} не поддерживается в preview"
                f" (используйте {NON_TENANT_SCOPE_TYPES})",
            )
        if not t.scope_value:
            raise HTTPException(
                400, f"target_scopes: пустой scope_value для {t.scope_type!r}"
            )
        targets.append((t.scope_type, t.scope_value))

    try:
        result = await compute_weights_preview(
            mode=payload.mode,
            target_scopes=targets,
            period_from=period_from,
            period_to=period_to,
            session=session,
        )
    except AllocationValidationError as ex:
        raise HTTPException(400, str(ex))

    return {
        "items": [
            {
                "scope_type": a.scope_type,
                "scope_value": a.scope_value,
                "weight": float(a.weight),
            }
            for a in result
        ],
        "period": {"from": period_from.isoformat(), "to": period_to.isoformat()},
        "mode": payload.mode,
    }
