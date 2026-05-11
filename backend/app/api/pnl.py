from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import current_brands_filter
from app.services.pnl_builder import build_pnl
from app.services.pnl_reconciliation import build_reconciliation

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("")
async def get_pnl(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    granularity: Literal["day", "week", "month"] = "day",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=29)
    out = await build_pnl(
        session,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        brands=brands,
    )
    out["scope"] = "company" if brands is None else "brands"
    return out


@router.get("/reconciliation")
async def get_reconciliation(
    weeks: int = Query(default=12, ge=1, le=52),
    diff_threshold_pct: float = Query(default=1.0, ge=0.0, le=100.0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Weekly reconciliation: WB seller-cabinet view vs our derived P&L."""
    out = await build_reconciliation(
        session,
        weeks_back=weeks,
        diff_threshold_pct=diff_threshold_pct,
        brands=brands,
    )
    out["scope"] = "company" if brands is None else "brands"
    return out
