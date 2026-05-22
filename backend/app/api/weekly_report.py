"""TASK-LEAD-061 — Multi-manager scoreboard для `/weekly-report`.

Endpoint:
  GET /api/weekly-report/by-manager?week_start=YYYY-MM-DD
  → [{manager_user_id, manager_name, brands: [...], revenue, margin,
       orders, returns, wow_revenue_pct, wow_margin_pct, ...}]

Доступ: только `director` / `head_of_sales`. Manager НЕ должен видеть
scoreboard коллег (его собственная неделя видна в основной части
`/weekly-report` через brand-filter).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.weekly_report import by_manager

log = get_logger(__name__)

router = APIRouter(prefix="/api/weekly-report", tags=["weekly-report"])


@router.get("/by-manager", dependencies=[Depends(require_director_or_head)])
async def weekly_report_by_manager(
    week_start: Annotated[date, Query(description="Понедельник недели (YYYY-MM-DD)")],
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Свод по менеджерам за указанную неделю (week_start = понедельник).

    WoW дельты считаются относительно предыдущей недели
    (`week_start - 7 дней`). Источник — `wb_report_detail` (mode=final),
    как Dashboard.
    """
    items = await by_manager(session, user.tenant_id, week_start)
    return {
        "week_start": week_start.isoformat(),
        "items": items,
    }
