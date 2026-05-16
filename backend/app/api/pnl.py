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
    compare: bool = Query(
        default=False,
        description=(
            "Если true — добавляет в ответ `previous` с totals за период такой "
            "же длины, сдвинутый назад. Для сравнения «текущий vs предыдущий»."
        ),
    ),
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

    if compare:
        # Период такой же длины, сдвинутый назад на (N+1) дней, чтобы прошлый
        # период не пересекался с текущим (включительные границы).
        n_days = (date_to - date_from).days
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n_days)
        prev = await build_pnl(
            session,
            date_from=prev_from,
            date_to=prev_to,
            granularity=granularity,
            brands=brands,
        )
        # Не возвращаем `rows` для прошлого периода — UI рисует только totals
        # в дополнительной колонке. Это бережёт payload и кеш.
        out["previous"] = {
            "from": prev["from"],
            "to": prev["to"],
            "totals": prev["totals"],
        }
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
