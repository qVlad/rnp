"""Налоговый отчёт по WB — endpoint для страницы /tax-report.

Воспроизводит методику клиентского бухгалтера 1:1 (см. services/tax_report.py).
Доступен только director/head_of_sales (это юридически чувствительные данные).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import current_brands_filter, get_db_tenant_scoped, require_director_or_head
from app.services.tax_report import build_tax_report

router = APIRouter(
    prefix="/api/tax-report",
    tags=["tax-report"],
    dependencies=[Depends(require_director_or_head)],
)


@router.get("")
async def get_tax_report(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Per-WB-realization tax report (Доход / Расход / Себестоимость / Налог).

    `from`/`to` фильтруют по `report_date_to` (дате признания дохода).
    По умолчанию — последние 90 дней.
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=89)
    out = await build_tax_report(
        session,
        date_from=date_from,
        date_to=date_to,
        brands=brands,
    )
    out["scope"] = "company" if brands is None else "brands"
    return out
