"""Ревизии WB-отчётов (TASK-DEV-095) — журнал переподгрузок истории.

Endpoints (director/head):
  GET  /api/data-revisions?source=&limit=          — список ревизий
  GET  /api/data-revisions/{id}/changes?offset=    — изменения ревизии (paged)
  POST /api/data-revisions/refetch {source, days_back}
       — ручной запуск переподгрузки для активного кабинета (Celery).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbSyncChange, WbSyncRevision
from app.services.auth import (
    CurrentUser,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.tenant_context import get_tenant

router = APIRouter(prefix="/api/data-revisions", tags=["data-revisions"])

SOURCES = ("report_detail", "ad_stats", "orders", "sales", "funnel")
# WB-лимиты глубины переподгрузки per source (funnel — rolling-7 жёстко).
MAX_DAYS_BACK = {
    "report_detail": 365,
    "ad_stats": 92,
    "orders": 90,
    "sales": 90,
    "funnel": 7,
}


class RefetchRequest(BaseModel):
    source: str
    days_back: int = Field(default=42, ge=1, le=365)


def _revision_dict(r: WbSyncRevision) -> dict[str, Any]:
    return {
        "id": r.id,
        "source": r.source,
        "period_from": r.period_from.isoformat(),
        "period_to": r.period_to.isoformat(),
        "status": r.status,
        "rows_fetched": r.rows_fetched,
        "rows_added": r.rows_added,
        "rows_changed": r.rows_changed,
        "rows_rejected": r.rows_rejected,
        "totals_delta": r.totals_delta,
        "error": r.error,
        "triggered_by": r.triggered_by,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get("")
async def list_revisions(
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(require_director_or_head),
) -> dict[str, Any]:
    stmt = select(WbSyncRevision)
    if source:
        stmt = stmt.where(WbSyncRevision.source == source)
    stmt = stmt.order_by(WbSyncRevision.started_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_revision_dict(r) for r in rows], "sources": list(SOURCES)}


@router.get("/{revision_id}/changes")
async def list_changes(
    revision_id: int,
    kind: str | None = Query(None, description="added|updated|rejected_lower"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(require_director_or_head),
) -> dict[str, Any]:
    revision = (
        await session.execute(
            select(WbSyncRevision).where(WbSyncRevision.id == revision_id)
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="revision_not_found")

    stmt = select(WbSyncChange).where(WbSyncChange.revision_id == revision_id)
    cnt_stmt = select(func.count()).select_from(WbSyncChange).where(
        WbSyncChange.revision_id == revision_id
    )
    if kind:
        stmt = stmt.where(WbSyncChange.change_kind == kind)
        cnt_stmt = cnt_stmt.where(WbSyncChange.change_kind == kind)
    total = (await session.execute(cnt_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(WbSyncChange.id).offset(offset).limit(limit)
        )
    ).scalars().all()
    return {
        "revision": _revision_dict(revision),
        "total": total,
        "offset": offset,
        "items": [
            {
                "id": c.id,
                "entity_key": c.entity_key,
                "change_kind": c.change_kind,
                "old": c.old,
                "new": c.new,
            }
            for c in rows
        ],
    }


@router.post("/refetch")
async def trigger_refetch(
    payload: RefetchRequest,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(require_director_or_head),
) -> dict[str, Any]:
    if payload.source not in SOURCES:
        raise HTTPException(status_code=422, detail=f"unknown source: {payload.source}")
    days_back = min(payload.days_back, MAX_DAYS_BACK[payload.source])
    tenant_id = get_tenant(session)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="no_active_tenant")
    # Ленивая отправка: celery-таск импортируется здесь, чтобы web-процесс
    # не тянул sync-модули при старте.
    from app.sync.tasks_refetch import refetch_source_for_tenant  # noqa: WPS433

    async_result = refetch_source_for_tenant.delay(
        tenant_id, payload.source, days_back, "manual"
    )
    return {
        "status": "queued",
        "task_id": async_result.id,
        "source": payload.source,
        "days_back": days_back,
        "tenant_id": tenant_id,
    }
