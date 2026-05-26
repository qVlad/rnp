"""API endpoint для leak-report «найдено N₽» (TASK-LEAD-140).

`GET /api/leak-report?from=&to=` — агрегированный аудит-отчёт: одно число
«найдено N₽» + breakdown по 5 источникам утечек + recon trust-badge.

Используется как ритуал входа в клуб (онбординг кабинета) и печатный
sales-артефакт. Guard `director_or_head` — отчёт показывает всю картину
кабинета (минусовые SKU, штрафы), для manager-scope урезается brand-фильтром,
но открывать его в UI по умолчанию имеет смысл владельцу/РОПу.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    current_brands_filter,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.leak_report import build_leak_report

router = APIRouter(prefix="/api/leak-report", tags=["leak-report"])


@router.get("", dependencies=[Depends(require_director_or_head)])
async def get_leak_report(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Аудит-отчёт «найдено N₽» за период (по умолчанию — последние 30 дней)."""
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=29)
    return await build_leak_report(
        session, date_from=date_from, date_to=date_to, brands=brands
    )
