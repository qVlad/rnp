"""Read-only audit log endpoint."""
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.db.session import get_db
from app.services.auth import require_director

router = APIRouter(
    prefix="/api/audit-log",
    tags=["audit-log"],
    dependencies=[Depends(require_director)],
)


@router.get("")
async def list_audit_log(
    table: str | None = Query(default=None, description="filter by table_name"),
    actor: str | None = Query(default=None),
    op: str | None = Query(default=None, description="create | update | delete"),
    entity_id: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if table:
        stmt = stmt.where(AuditLog.table_name == table)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if op:
        stmt = stmt.where(AuditLog.op == op)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if date_from:
        stmt = stmt.where(
            AuditLog.created_at >= datetime.combine(date_from, datetime.min.time())
        )
    if date_to:
        stmt = stmt.where(
            AuditLog.created_at < datetime.combine(date_to, datetime.max.time())
        )

    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "actor": r.actor,
                "table": r.table_name,
                "op": r.op,
                "entity_id": r.entity_id,
                "before": r.before,
                "after": r.after,
                "source": r.source,
                "comment": r.comment,
            }
            for r in rows
        ],
        "limit": limit,
        "filters": {
            "table": table,
            "actor": actor,
            "op": op,
            "entity_id": entity_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
    }


@router.get("/tables")
async def list_audited_tables(session: AsyncSession = Depends(get_db)) -> dict[str, list[str]]:
    """Distinct table names that have ever been audited (for UI dropdown)."""
    rows = (
        await session.execute(
            select(AuditLog.table_name).distinct().order_by(AuditLog.table_name)
        )
    ).scalars().all()
    return {"items": list(rows)}
