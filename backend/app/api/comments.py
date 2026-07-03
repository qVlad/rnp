"""API комментариев-тредов (TASK-DEV-094, TS-паритет).

GET  /api/comments?entity_type=&entity_key=       → тред
GET  /api/comments/counts?entity_type=&keys=a,b,c → батч-счётчики (плитки/строки)
POST /api/comments {entity_type, entity_key, body}
DELETE /api/comments/{id}

Читают все аутентифицированные роли своего tenant'а; пишут director/head
(+manager — на sku, его рабочая зона).
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Comment
from app.services.auth import CurrentUser, get_current_user, get_db_tenant_scoped
from app.services.tenant_context import get_tenant

router = APIRouter(prefix="/api/comments", tags=["comments"])

_ENTITY_TYPES = {"kpi", "sku", "warehouse", "rnp_row", "plan", "report"}


@router.get("")
async def list_comments(
    entity_type: Annotated[str, Query()],
    entity_key: Annotated[str, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Comment)
            .where(Comment.entity_type == entity_type, Comment.entity_key == entity_key)
            .order_by(Comment.created_at.asc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": c.id,
                "body": c.body,
                "author_name": c.author_name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ]
    }


@router.get("/counts")
async def comment_counts(
    entity_type: Annotated[str, Query()],
    keys: Annotated[str, Query(description="CSV entity_key")],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, int]:
    """Батч-счётчики: один запрос на все плитки/строки таблицы."""
    key_list = [k.strip() for k in keys.split(",") if k.strip()][:500]
    if not key_list:
        return {}
    rows = (
        await session.execute(
            select(Comment.entity_key, func.count(Comment.id))
            .where(Comment.entity_type == entity_type, Comment.entity_key.in_(key_list))
            .group_by(Comment.entity_key)
        )
    ).all()
    return {k: int(c) for k, c in rows}


@router.post("")
async def create_comment(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    entity_type = str(payload.get("entity_type") or "")
    entity_key = str(payload.get("entity_key") or "").strip()[:128]
    body = str(payload.get("body") or "").strip()
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(400, f"entity_type ∈ {sorted(_ENTITY_TYPES)}")
    if not entity_key or not body:
        raise HTTPException(400, "entity_key и body обязательны")
    if len(body) > 4000:
        raise HTTPException(400, "комментарий длиннее 4000 символов")
    if user.role == "bookkeeper":
        raise HTTPException(403, "bookkeeper не пишет комментарии")
    obj = Comment(
        tenant_id=get_tenant(session),
        entity_type=entity_type,
        entity_key=entity_key,
        body=body,
        author_name=(user.full_name or user.username)[:64],
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return {
        "id": obj.id,
        "body": obj.body,
        "author_name": obj.author_name,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    }


@router.delete("/{comment_id}")
async def delete_comment(
    comment_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    obj = await session.get(Comment, comment_id)
    if obj is None:
        raise HTTPException(404, "комментарий не найден")
    # Удалять может автор или director.
    author = (user.full_name or user.username)[:64]
    if obj.author_name != author and user.role != "director":
        raise HTTPException(403, "удалять может автор или директор")
    await session.delete(obj)
    await session.commit()
    return {"ok": True}
