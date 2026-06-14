"""Команд-аннотации на дату (DEV-081, TS-parity «комментарии-маркеры»).

Заметка привязана к дате (запуск рекламы / смена цены / поставка / промо) и
рисуется маркером на timeseries-графиках (дашборд). Видна всей команде.

Endpoints:
  GET    /api/annotations?from=YYYY-MM-DD&to=YYYY-MM-DD  — список за период (все роли)
  POST   /api/annotations  {dt, text}                    — создать (director/head)
  DELETE /api/annotations/{id}                            — удалить (director/head)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChartAnnotation
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.tenant_context import get_tenant

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


class AnnotationCreate(BaseModel):
    dt: date
    text: str = Field(min_length=1, max_length=2000)


@router.get("")
async def list_annotations(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(ChartAnnotation)
    if from_ is not None:
        stmt = stmt.where(ChartAnnotation.dt >= from_)
    if to is not None:
        stmt = stmt.where(ChartAnnotation.dt <= to)
    stmt = stmt.order_by(ChartAnnotation.dt)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "dt": r.dt.isoformat(),
                "text": r.text,
                "author_name": r.author_name,
            }
            for r in rows
        ]
    }


@router.post("", dependencies=[Depends(require_director_or_head)])
async def create_annotation(
    payload: AnnotationCreate,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id = get_tenant(session) or user.tenant_id
    ann = ChartAnnotation(
        tenant_id=tenant_id,
        dt=payload.dt,
        text=payload.text.strip(),
        author_name=user.username,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ann)
    await session.commit()
    return {"id": ann.id, "status": "created"}


@router.delete("/{ann_id}", dependencies=[Depends(require_director_or_head)])
async def delete_annotation(
    ann_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    res = await session.execute(
        delete(ChartAnnotation).where(ChartAnnotation.id == ann_id)
    )
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "annotation not found")
    return {"status": "deleted"}
