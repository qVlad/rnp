"""API для пользовательских формул KPI (TASK-DEV-011).

GET    /api/metric-templates              — список (tenant-scoped)
POST   /api/metric-templates              — создать (только director)
PUT    /api/metric-templates/{id}         — обновить (только director)
DELETE /api/metric-templates/{id}         — удалить (только director)
GET    /api/metric-templates/evaluate     — список с посчитанными значениями
                                            для текущего периода (для Dashboard)
GET    /api/metric-templates/variables    — список переменных + описаний
POST   /api/metric-templates/preview      — превью одной формулы (validate + eval)
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MetricTemplate
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
)
from app.services.custom_metrics import (
    AVAILABLE_VARIABLES,
    SafeEvalError,
    extract_kpi_context,
    safe_eval,
)
from app.services.metrics import compute_dashboard
from app.services.periods import get_period

router = APIRouter(prefix="/api/metric-templates", tags=["metric-templates"])


class MetricTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    formula: str = Field(min_length=1, max_length=2000)
    format: Literal["currency", "percent", "number"] = "number"
    description: str | None = None


def _to_out(m: MetricTemplate) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "formula": m.formula,
        "format": m.format,
        "description": m.description,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("")
async def list_templates(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(select(MetricTemplate).order_by(MetricTemplate.name))
    ).scalars().all()
    return {"items": [_to_out(m) for m in rows]}


@router.get("/variables")
async def list_variables() -> dict[str, Any]:
    """Список переменных для UI builder'а — отображается как dropdown."""
    return {
        "variables": [
            {"key": k, "description": v}
            for k, v in AVAILABLE_VARIABLES.items()
        ],
        "functions": ["abs", "min", "max", "round", "int", "float"],
    }


class PreviewIn(BaseModel):
    formula: str


@router.post("/preview")
async def preview_formula(
    body: PreviewIn,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Превью: проверить формулу + посчитать значение на текущей неделе."""
    dash = await compute_dashboard(session, get_period("week"), brands=brands)
    ctx = extract_kpi_context(dash.get("kpis", []))
    try:
        value = safe_eval(body.formula, ctx)
        return {"ok": True, "value": value, "context": ctx}
    except SafeEvalError as e:
        return {"ok": False, "error": str(e)}


@router.get("/evaluate")
async def evaluate_all(
    period: Annotated[Literal["day", "week", "month"], Query()] = "week",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Получить все templates тенанта с посчитанными значениями за период.

    Подмешивается в Dashboard как блок «Кастомные KPI». Каждая template даёт
    одну строку: name + value + format. Если формула сломана — error в строке.
    """
    rows = (
        await session.execute(select(MetricTemplate).order_by(MetricTemplate.name))
    ).scalars().all()
    if not rows:
        return {"period": period, "items": []}
    dash = await compute_dashboard(session, get_period(period), brands=brands)
    ctx = extract_kpi_context(dash.get("kpis", []))
    items = []
    for m in rows:
        try:
            value = safe_eval(m.formula, ctx)
            items.append({
                "id": m.id,
                "name": m.name,
                "formula": m.formula,
                "format": m.format,
                "description": m.description,
                "value": value,
                "error": None,
            })
        except SafeEvalError as e:
            items.append({
                "id": m.id,
                "name": m.name,
                "formula": m.formula,
                "format": m.format,
                "description": m.description,
                "value": None,
                "error": str(e),
            })
    return {"period": period, "items": items}


@router.post("", dependencies=[Depends(require_director)])
async def create_template(
    body: MetricTemplateIn,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        safe_eval(body.formula, {k: 0.0 for k in AVAILABLE_VARIABLES})
    except SafeEvalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    m = MetricTemplate(
        tenant_id=user.tenant_id,
        name=body.name,
        formula=body.formula,
        format=body.format,
        description=body.description,
        created_by_user_id=user.id,
    )
    session.add(m)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось создать (имя должно быть уникальным): {e}",
        )
    await session.refresh(m)
    return _to_out(m)


@router.put("/{template_id}", dependencies=[Depends(require_director)])
async def update_template(
    template_id: int,
    body: MetricTemplateIn,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    m = (await session.execute(
        select(MetricTemplate).where(MetricTemplate.id == template_id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    try:
        safe_eval(body.formula, {k: 0.0 for k in AVAILABLE_VARIABLES})
    except SafeEvalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    m.name = body.name
    m.formula = body.formula
    m.format = body.format
    m.description = body.description
    m.updated_at = datetime.now()
    await session.commit()
    await session.refresh(m)
    return _to_out(m)


@router.delete("/{template_id}", dependencies=[Depends(require_director)])
async def delete_template(
    template_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    m = (await session.execute(
        select(MetricTemplate).where(MetricTemplate.id == template_id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(m)
    await session.commit()
    return {"ok": True}
