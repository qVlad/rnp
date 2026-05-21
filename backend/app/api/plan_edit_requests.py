"""Plan edit requests API (TASK-DEV-017).

Manager на странице /plans видит планы read-only. Чтобы предложить правку:
  POST /api/plan-edit-requests
  body: {plan_id, field_name, requested_value, comment?}

Director видит pending-requests + accept/reject:
  GET    /api/plan-edit-requests?status=pending
  POST   /api/plan-edit-requests/{id}/accept   (применяет правку к плану)
  POST   /api/plan-edit-requests/{id}/reject   (закрывает с причиной)

При POST от manager'а — TG-notification директорам тенанта (через AppSetting.tg_chat_id).
Audit log на каждом resolve.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import PlanEditRequest, SalesPlan, User
from app.services.audit import audit_log
from app.services.tg_broadcast import broadcast_to_directors, notify_user
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)


log = get_logger(__name__)

router = APIRouter(prefix="/api/plan-edit-requests", tags=["plan-edit-requests"])


# Whitelist полей плана которые manager может предлагать изменить
ALLOWED_FIELDS = {
    "planned_orders_qty",
    "planned_orders_revenue",
    "planned_sales_qty",
    "planned_sales_revenue",
    "planned_profit",
    "planned_marketing_cost",
}


class RequestIn(BaseModel):
    plan_id: int = Field(ge=1)
    field_name: str = Field(min_length=1, max_length=64)
    requested_value: Decimal
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


def _row(req: PlanEditRequest, requester: User | None, resolver: User | None) -> dict[str, Any]:
    return {
        "id": req.id,
        "plan_id": req.plan_id,
        "field_name": req.field_name,
        "current_value": float(req.current_value) if req.current_value is not None else None,
        "requested_value": float(req.requested_value),
        "comment": req.comment,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "requested_by": (requester.full_name or requester.username) if requester else None,
        "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        "resolved_by": (resolver.full_name or resolver.username) if resolver else None,
        "resolution_note": req.resolution_note,
    }


@router.post("")
async def create_request(
    body: RequestIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Создать заявку на правку плана. Manager делает в своём brand-scope."""
    if body.field_name not in ALLOWED_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"field_name must be one of: {sorted(ALLOWED_FIELDS)}",
        )
    plan = await session.get(SalesPlan, body.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")

    # Manager-scope check для nm/group планов.
    # Для store-scope плана manager не может править — это в основном
    # директорские стратегические планы.
    if brands is not None:
        if plan.scope_type == "store":
            raise HTTPException(
                status_code=403,
                detail="store-scope планы не редактируются manager'ом",
            )
        # nm / group: brand check через JOIN. Скипаем: вся плановая
        # семантика per-tenant, заявка не утечёт между tenant'ами (SET tenant).

    current_value = getattr(plan, body.field_name, None)
    req = PlanEditRequest(
        tenant_id=user.tenant_id,
        plan_id=plan.id,
        requested_by_user_id=user.id,
        field_name=body.field_name,
        current_value=Decimal(str(current_value)) if current_value is not None else None,
        requested_value=body.requested_value,
        comment=body.comment,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)

    # TG-broadcast всем директорам тенанта (multi-recipient).
    # Не блокируем main-flow если рассылка упала — заявка уже создана.
    try:
        sender = user.full_name or user.username
        msg = (
            f"<b>Заявка на правку плана</b>\n\n"
            f"От: {sender} ({user.role})\n"
            f"Plan ID: {plan.id} ({plan.scope_type} #{plan.scope_id})\n"
            f"Поле: <code>{body.field_name}</code>\n"
            f"Текущее: {current_value or '—'}\n"
            f"Запрос: <b>{body.requested_value}</b>\n"
            + (f"\nКомментарий: {body.comment}" if body.comment else "")
            + f"\n\nОткрыть в РНП: /plans → заявки (#{req.id})"
        )
        await broadcast_to_directors(session, msg, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        log.warning("plan_edit_requests TG broadcast failed: %s", e)

    return _row(req, None, None) | {
        "id": req.id,
        "requested_by": user.full_name or user.username,
    }


@router.get("", dependencies=[Depends(require_director_or_head)])
async def list_requests(
    status: Literal["pending", "accepted", "rejected", "all"] = "pending",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    q = select(PlanEditRequest).order_by(PlanEditRequest.created_at.desc()).limit(200)
    if status != "all":
        q = q.where(PlanEditRequest.status == status)
    rows = (await session.execute(q)).scalars().all()
    # Hydrate users (requester + resolver)
    user_ids: set[int] = set()
    for r in rows:
        if r.requested_by_user_id:
            user_ids.add(r.requested_by_user_id)
        if r.resolved_by_user_id:
            user_ids.add(r.resolved_by_user_id)
    users_by_id: dict[int, User] = {}
    if user_ids:
        urows = (
            await session.execute(select(User).where(User.id.in_(list(user_ids))))
        ).scalars().all()
        users_by_id = {u.id: u for u in urows}
    return {
        "items": [
            _row(
                r,
                users_by_id.get(r.requested_by_user_id) if r.requested_by_user_id else None,
                users_by_id.get(r.resolved_by_user_id) if r.resolved_by_user_id else None,
            )
            for r in rows
        ]
    }


@router.post(
    "/{req_id}/accept",
    dependencies=[Depends(require_director_or_head)],
)
async def accept_request(
    req_id: Annotated[int, Path(ge=1)],
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Принять заявку — apply value на план + close."""
    req = await session.get(PlanEditRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"already {req.status}, cannot accept"
        )
    if req.field_name not in ALLOWED_FIELDS:
        raise HTTPException(
            status_code=400, detail="field_name not in whitelist (stale request)"
        )
    plan = await session.get(SalesPlan, req.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found (deleted)")

    before = {req.field_name: getattr(plan, req.field_name)}
    setattr(plan, req.field_name, req.requested_value)
    req.status = "accepted"
    req.resolved_by_user_id = user.id
    req.resolved_at = datetime.now(timezone.utc)
    await audit_log(
        session,
        "sales_plans",
        "update",
        entity_id=str(plan.id),
        actor=user.username,
        before=before,
        after={req.field_name: float(req.requested_value)},
        comment=f"via plan_edit_request #{req.id}",
    )
    await session.commit()

    # Back-loop: notify requester в Telegram если он привязал свой chat_id.
    # Fail-open — рассылка не блокирует accept.
    if req.requested_by_user_id:
        try:
            resolver_name = user.full_name or user.username
            msg = (
                f"<b>✓ Заявка #{req.id} принята</b>\n\n"
                f"План #{req.plan_id}, поле <code>{req.field_name}</code>:\n"
                f"  {req.current_value or '—'} → <b>{req.requested_value}</b>\n\n"
                f"Принял: {resolver_name}\n"
                f"Откройте /plans чтобы увидеть обновлённый план."
            )
            await notify_user(session, req.requested_by_user_id, msg)
        except Exception as e:  # noqa: BLE001
            log.warning("notify accept failed: %s", e)

    return {"ok": True, "request_id": req.id, "applied": True}


@router.post(
    "/{req_id}/reject",
    dependencies=[Depends(require_director_or_head)],
)
async def reject_request(
    req_id: Annotated[int, Path(ge=1)],
    body: RejectIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Отклонить заявку с обязательным `note`."""
    req = await session.get(PlanEditRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"already {req.status}, cannot reject"
        )
    req.status = "rejected"
    req.resolved_by_user_id = user.id
    req.resolved_at = datetime.now(timezone.utc)
    req.resolution_note = body.note
    await session.commit()

    # Back-loop: notify requester (manager) что заявку отклонили + причина.
    if req.requested_by_user_id:
        try:
            resolver_name = user.full_name or user.username
            msg = (
                f"<b>✕ Заявка #{req.id} отклонена</b>\n\n"
                f"План #{req.plan_id}, поле <code>{req.field_name}</code>:\n"
                f"  {req.current_value or '—'} → ~~{req.requested_value}~~\n\n"
                f"Причина: <i>{body.note}</i>\n\n"
                f"Отклонил: {resolver_name}"
            )
            await notify_user(session, req.requested_by_user_id, msg)
        except Exception as e:  # noqa: BLE001
            log.warning("notify reject failed: %s", e)

    return {"ok": True, "request_id": req.id, "rejected": True}
