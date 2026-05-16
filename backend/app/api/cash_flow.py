"""Cash Flow Statement (ДДС) — single endpoint."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import require_director_or_head
from app.services.cash_flow import build_cash_flow
from app.services.payment_calendar import build_payment_calendar

router = APIRouter(
    prefix="/api/cash-flow",
    tags=["cash-flow"],
    dependencies=[Depends(require_director_or_head)],
)


@router.get("")
async def cash_flow(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    session: AsyncSession = Depends(get_db_tenant_scoped),
):
    return await build_cash_flow(session, date_from=date_from, date_to=date_to)


@router.get("/calendar")
async def cash_flow_calendar(
    days_forward: Annotated[int, Query(ge=1, le=180)] = 30,
    pay_offset_days: Annotated[int, Query(ge=0, le=60)] = 14,
    initial_balance: Annotated[float | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
):
    """Платёжный календарь — прогноз банковского остатка на N дней.

    - `days_forward` — горизонт прогноза (default 30 дн).
    - `pay_offset_days` — лаг WB-выплат от report_date_to (default 14).
    - `initial_balance` — начальный остаток на счёте. Если null —
      берётся `app_settings.bank_balance_current`, иначе 0.
    """
    return await build_payment_calendar(
        session,
        days_forward=days_forward,
        pay_offset_days=pay_offset_days,
        initial_balance=initial_balance,
    )
