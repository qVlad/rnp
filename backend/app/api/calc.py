"""Reference data for the unit-economics what-if calculator.

The calculator itself runs in the browser (so it can be live-reactive without
network round-trips). This endpoint just provides the reference catalog of
tariff categories with their default commission and logistics values.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, WbTariffCategory
from app.db.session import get_db

router = APIRouter(prefix="/api/calc", tags=["calc"])


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(WbTariffCategory).order_by(
                WbTariffCategory.sort_order, WbTariffCategory.name
            )
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "commission_pct": float(r.commission_pct or 0),
                "default_logistics_per_unit": float(r.default_logistics_per_unit or 0),
            }
            for r in rows
        ]
    }


@router.get("/defaults")
async def calc_defaults(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return the user's tax/VAT settings so the calculator can pre-fill them."""
    rows = (await session.execute(select(AppSetting))).scalars().all()
    cfg = {r.key: r.value or "" for r in rows}

    def _f(v: Any, d: float = 0) -> float:
        try:
            return float(v) if v else d
        except (ValueError, TypeError):
            return d

    return {
        "tax_system": cfg.get("tax_system", "none"),
        "tax_rate": _f(cfg.get("tax_rate"), 6),
        "tax_min_rate": _f(cfg.get("tax_min_rate"), 1),
        "vat_payer": (cfg.get("vat_payer") or "0") == "1",
        "vat_rate": _f(cfg.get("vat_rate"), 0),
        "acquiring_pct": 1.5,  # typical WB seller acquiring fee
    }
