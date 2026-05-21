"""Period A vs Period B comparison for Dashboard (TASK-LEAD-029).

Returns KPIs computed for two arbitrary date ranges plus a delta-percent map
keyed by KPI key. The KPI list is reused from `compute_dashboard` — same
formulas, same tooltips, same modes (preliminary / final / hybrid).

Delta semantics:
    delta_pct = (a.value - b.value) / b.value * 100
where `a` is the period the user is comparing FROM (period_a), and `b` is the
baseline (period_b). If b.value == 0 → delta_pct = None (no divide-by-zero).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db  # noqa: F401  # re-exported for test patching
from app.services.auth import current_brands_filter, get_db_tenant_scoped
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _delta_pct(a: float | None, b: float | None) -> float | None:
    """((a − b) / b) × 100. Returns None when b is 0/None/non-numeric."""
    if a is None or b is None:
        return None
    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return None
    if bf == 0:
        return None
    return round((af - bf) / bf * 100, 2)


def _build_delta_map(
    kpis_a: list[dict], kpis_b: list[dict]
) -> dict[str, float | None]:
    by_b: dict[str, float | None] = {k["key"]: k.get("value") for k in kpis_b}
    out: dict[str, float | None] = {}
    for k in kpis_a:
        out[k["key"]] = _delta_pct(k.get("value"), by_b.get(k["key"]))
    return out


@router.get("/compare")
async def compare_periods(
    a_from: Annotated[date, Query(description="Period A start (inclusive)")],
    a_to: Annotated[date, Query(description="Period A end (inclusive)")],
    b_from: Annotated[date, Query(description="Period B start (inclusive)")],
    b_to: Annotated[date, Query(description="Period B end (inclusive)")],
    mode: Literal["preliminary", "final", "hybrid"] = "preliminary",
    reporting_mode: Literal["operational", "financial"] = "operational",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    try:
        p_a = period_from_range(a_from, a_to)
        p_b = period_from_range(b_from, b_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dash_a = await compute_dashboard(
        session, p_a, brands=brands, mode=mode, reporting_mode=reporting_mode,
    )
    dash_b = await compute_dashboard(
        session, p_b, brands=brands, mode=mode, reporting_mode=reporting_mode,
    )

    return {
        "mode": mode,
        "reporting_mode": reporting_mode,
        "period_a": dash_a,
        "period_b": dash_b,
        "delta_pct": _build_delta_map(dash_a.get("kpis", []), dash_b.get("kpis", [])),
    }
