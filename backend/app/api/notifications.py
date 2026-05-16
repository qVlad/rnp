"""Notification rules — CRUD + manual evaluation.

User создаёт правила вида «если остаток SKU < 50 → telegram». Engine
(`services/notification_engine.py`) запускается Celery beat'ом раз в час
и проверяет все active rules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationRule
from app.services.auth import CurrentUser, get_current_user, get_db_tenant_scoped
from app.services.notification_engine import evaluate_all_rules

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

ALLOWED_METRICS = {
    "stock_below",
    "daily_revenue_below",
    "drr_above",
    "returns_pct_above",
}
ALLOWED_OPS = {"<", ">", "<=", ">="}


def _to_dict(r: NotificationRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "metric": r.metric,
        "operator": r.operator,
        "threshold": float(r.threshold),
        "scope_filter": r.scope_filter,
        "channel": r.channel,
        "is_active": bool(r.is_active),
        "cooldown_minutes": int(r.cooldown_minutes),
        "last_fired_at": r.last_fired_at.isoformat() if r.last_fired_at else None,
        "last_fire_payload": r.last_fire_payload,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/rules")
async def list_rules(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(NotificationRule).order_by(NotificationRule.is_active.desc(), NotificationRule.name)
        )
    ).scalars().all()
    return {"items": [_to_dict(r) for r in rows], "allowed_metrics": sorted(ALLOWED_METRICS)}


@router.post("/rules")
async def create_rule(
    name: str = Body(..., embed=True),
    metric: str = Body(..., embed=True),
    operator: str = Body(..., embed=True),
    threshold: float = Body(..., embed=True),
    scope_filter: dict | None = Body(default=None, embed=True),
    channel: str = Body(default="telegram", embed=True),
    cooldown_minutes: int = Body(default=1440, embed=True),
    is_active: bool = Body(default=True, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if metric not in ALLOWED_METRICS:
        raise HTTPException(400, f"metric должен быть одним из {sorted(ALLOWED_METRICS)}")
    if operator not in ALLOWED_OPS:
        raise HTTPException(400, f"operator должен быть одним из {sorted(ALLOWED_OPS)}")
    if channel != "telegram":
        raise HTTPException(400, "Пока поддержан только telegram канал")
    rule = NotificationRule(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=name.strip()[:128],
        metric=metric,
        operator=operator,
        threshold=threshold,
        scope_filter=scope_filter,
        channel=channel,
        is_active=is_active,
        cooldown_minutes=max(60, cooldown_minutes),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _to_dict(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    name: str | None = Body(default=None, embed=True),
    threshold: float | None = Body(default=None, embed=True),
    operator: str | None = Body(default=None, embed=True),
    scope_filter: dict | None = Body(default=None, embed=True),
    is_active: bool | None = Body(default=None, embed=True),
    cooldown_minutes: int | None = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    rule = await session.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Не найдено")
    if name is not None:
        rule.name = name.strip()[:128]
    if threshold is not None:
        rule.threshold = threshold
    if operator is not None:
        if operator not in ALLOWED_OPS:
            raise HTTPException(400, "Bad operator")
        rule.operator = operator
    if scope_filter is not None:
        rule.scope_filter = scope_filter
    if is_active is not None:
        rule.is_active = is_active
    if cooldown_minutes is not None:
        rule.cooldown_minutes = max(60, cooldown_minutes)
    rule.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(rule)
    return _to_dict(rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    rule = await session.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Не найдено")
    await session.delete(rule)
    await session.commit()
    return {"status": "ok"}


@router.post("/evaluate")
async def evaluate_now(
    dry_run: bool = Body(default=True, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Manual trigger evaluation. По умолчанию `dry_run=true` — НЕ
    отправляет уведомления, только показывает что бы сработало.
    """
    evals = await evaluate_all_rules(session, dry_run=dry_run)
    return {
        "dry_run": dry_run,
        "evaluations": [
            {
                "rule_id": e.rule_id,
                "rule_name": e.rule_name,
                "triggered": e.triggered,
                "hits_count": len(e.payload.get("hits", [])),
                "message": e.message,
            }
            for e in evals
        ],
    }
