"""Чарджбэки / штрафы WB API.

См. spec: `agents/references/spec-chargebacks.md` (LEAD-005).

Все ручки за `require_module("chargebacks")` — модуль включается per-tenant.
Все мутации — `require_director_or_head`. Удаление НЕ предусмотрено (только
переход в статус `cancelled`).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chargeback, ChargebackHistory
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.chargebacks import (
    CATEGORY_LABELS,
    INCOME_CATEGORIES,
    STATUS_LABELS,
    TransitionError,
    sync_chargebacks,
    transition,
)
from app.services.feature_flags import require_module


router = APIRouter(
    prefix="/api/chargebacks",
    tags=["chargebacks"],
    dependencies=[
        Depends(require_module("chargebacks")),
        Depends(require_director_or_head),
    ],
)


def _serialize_chargeback(c: Chargeback) -> dict[str, Any]:
    return {
        "id": c.id,
        "rrd_id": c.rrd_id,
        "category": c.category,
        "category_label": CATEGORY_LABELS.get(c.category, c.category),
        "is_income": c.category in INCOME_CATEGORIES,
        "supplier_oper_name": c.supplier_oper_name,
        "amount_rub": float(c.amount_rub),
        "nm_id": c.nm_id,
        "status": c.status,
        "status_label": STATUS_LABELS.get(c.status, c.status),
        "operation_dt": c.operation_dt.isoformat() if c.operation_dt else None,
        "rr_dt": c.rr_dt.isoformat() if c.rr_dt else None,
        "comment": c.comment,
        "claim_text": c.claim_text,
        "claim_filed_at": c.claim_filed_at.isoformat() if c.claim_filed_at else None,
        "wb_response": c.wb_response,
        "wb_responded_at": c.wb_responded_at.isoformat() if c.wb_responded_at else None,
        "recovered_amount": float(c.recovered_amount) if c.recovered_amount else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "created_by": c.created_by,
        "updated_by": c.updated_by,
    }


@router.get("")
async def list_chargebacks(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список чарджбэков с фильтрами. Сортировка по operation_dt DESC."""
    stmt = select(Chargeback)
    if status:
        stmt = stmt.where(Chargeback.status == status)
    if category:
        stmt = stmt.where(Chargeback.category == category)
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Chargeback.amount_rub >= Decimal(str(min_amount)))
    stmt = stmt.order_by(Chargeback.operation_dt.desc().nullslast(), Chargeback.id.desc())
    stmt = stmt.limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_chargeback(c) for c in rows], "limit": limit, "offset": offset}


@router.get("/stats")
async def get_stats(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сводка по категориям × статусам за период.

    Возвращает таблицу: для каждой категории — count и sum(amount) по статусам.
    """
    stmt = select(
        Chargeback.category,
        Chargeback.status,
        func.count(Chargeback.id).label("cnt"),
        func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
    ).group_by(Chargeback.category, Chargeback.status)
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    rows = (await session.execute(stmt)).all()
    by_cat: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = by_cat.setdefault(
            r.category,
            {
                "category": r.category,
                "category_label": CATEGORY_LABELS.get(r.category, r.category),
                "is_income": r.category in INCOME_CATEGORIES,
                "by_status": {},
                "total_count": 0,
                "total_amount": 0.0,
            },
        )
        cat["by_status"][r.status] = {
            "count": int(r.cnt),
            "amount": float(r.total),
        }
        cat["total_count"] += int(r.cnt)
        cat["total_amount"] += float(r.total)
    return {"by_category": list(by_cat.values())}


@router.get("/{cid}")
async def get_chargeback(
    cid: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    c = (
        await session.execute(select(Chargeback).where(Chargeback.id == cid))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    # История переходов
    hist_rows = (
        await session.execute(
            select(ChargebackHistory)
            .where(ChargebackHistory.chargeback_id == cid)
            .order_by(ChargebackHistory.created_at.desc())
        )
    ).scalars().all()
    return {
        **_serialize_chargeback(c),
        "history": [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "comment": h.comment,
                "actor": h.actor,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hist_rows
        ],
    }


@router.put("/{cid}")
async def update_chargeback(
    cid: int,
    comment: str | None = Body(default=None, embed=True),
    claim_text: str | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Обновить свободные поля — comment, claim_text. Не меняет статус."""
    c = (
        await session.execute(select(Chargeback).where(Chargeback.id == cid))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    if comment is not None:
        c.comment = comment
    if claim_text is not None:
        c.claim_text = claim_text
    c.updated_by = user.username
    await audit_log(
        session,
        "chargebacks",
        "update",
        entity_id=str(cid),
        after={"comment": comment, "claim_text": claim_text},
        actor=user.username,
    )
    await session.commit()
    return _serialize_chargeback(c)


@router.post("/{cid}/transition")
async def transition_chargeback(
    cid: int,
    to_status: str = Body(..., embed=True),
    comment: str | None = Body(default=None, embed=True),
    wb_response: str | None = Body(default=None, embed=True),
    recovered_amount: float | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Перевод статуса с проверкой statemachine."""
    c = (
        await session.execute(select(Chargeback).where(Chargeback.id == cid))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    try:
        await transition(
            session,
            chargeback=c,
            to_status=to_status,
            actor=user.username,
            comment=comment,
            wb_response=wb_response,
            recovered_amount=Decimal(str(recovered_amount))
            if recovered_amount is not None
            else None,
        )
    except TransitionError as e:
        raise HTTPException(400, str(e))
    await audit_log(
        session,
        "chargebacks",
        "transition",
        entity_id=str(cid),
        after={
            "to_status": to_status,
            "comment": comment,
            "wb_response": wb_response,
            "recovered_amount": recovered_amount,
        },
        actor=user.username,
    )
    await session.commit()
    return _serialize_chargeback(c)


@router.post("/sync")
async def trigger_sync(
    lookback_days: int = Body(default=60, embed=True, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Ручной запуск парсера — сканирует wb_report_detail за lookback_days
    и создаёт новые chargebacks. Идемпотентен (UNIQUE по rrd_id+category).
    """
    result = await sync_chargebacks(
        session,
        tenant_id=user.tenant_id,
        lookback_days=lookback_days,
    )
    await audit_log(
        session,
        "chargebacks",
        "sync",
        after=result,
        actor=user.username,
    )
    await session.commit()
    return result


@router.get("/meta/categories")
async def list_categories() -> dict[str, Any]:
    """Канонический список категорий + статусов для UI dropdown'ов."""
    return {
        "categories": [
            {
                "code": code,
                "label": label,
                "is_income": code in INCOME_CATEGORIES,
            }
            for code, label in CATEGORY_LABELS.items()
        ],
        "statuses": [{"code": code, "label": label} for code, label in STATUS_LABELS.items()],
    }
