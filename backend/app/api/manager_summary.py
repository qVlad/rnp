"""TASK-LEAD-106 — `/api/manager-summary` aggregate endpoint.

Один endpoint композирует всё, что фронтенд `ManagerSummary.tsx` ранее
дергал 5+ независимыми запросами:
  - scoreboard row (revenue / margin / WoW)
  - top SKUs by revenue + by margin (brand-scope)
  - top-N recommendations (brand-scope)
  - system-wide alerts
  - per-week комментарии (overall + per-brand)

RBAC: `require_manager_access` (TASK-LEAD-107):
  - manager-as-self → разрешено (`target_user_id == caller.id`)
  - director / head_of_sales → могут смотреть любого менеджера в своём
    кабинете (`tenant_id` matches)
  - cross-tenant → 403 даже для director'а

Если caller != target (РОП открыл чужой scope) — пишем audit-log событие
`access.manager_summary_view`.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.audit import actor_from_request, audit_log
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_manager_access,
)
from app.services.manager_summary import (
    ManagerSummaryResponse,
    build_manager_summary,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/manager-summary", tags=["manager-summary"])


@router.get("", response_model=ManagerSummaryResponse)
@router.get("/", response_model=ManagerSummaryResponse)
async def get_manager_summary(
    request: Request,
    manager_user_id: Annotated[
        int, Query(description="ID менеджера, чей scope открываем")
    ],
    week_start: Annotated[
        date, Query(description="Понедельник недели (YYYY-MM-DD)")
    ],
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> ManagerSummaryResponse:
    """Composite endpoint для ManagerSummary page.

    Возвращает {manager, scoreboard, top_revenue, top_margin, recommendations,
    alerts, comments}. См. `services/manager_summary.py` для деталей.
    """
    # RBAC guard — кидает 403 если caller не имеет доступа.
    target = await require_manager_access(manager_user_id, user, session)

    # Audit-log: РОП смотрит чужой scope.
    if int(target.id) != int(user.id):
        try:
            await audit_log(
                session,
                "users",
                "access.manager_summary_view",
                entity_id=str(target.id),
                actor=actor_from_request(request),
                after={
                    "viewed_manager_id": int(target.id),
                    "viewed_manager_username": target.username,
                    "week_start": week_start.isoformat(),
                },
            )
        except Exception:  # noqa: BLE001
            # Audit-log не должен ломать read-only endpoint.
            log.warning(
                "manager_summary: audit_log failed (non-fatal)",
                exc_info=True,
            )

    return await build_manager_summary(
        session,
        tenant_id=user.tenant_id,
        manager_user_id=int(target.id),
        week_start=week_start,
        caller=user,
    )
