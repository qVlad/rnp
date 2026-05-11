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
