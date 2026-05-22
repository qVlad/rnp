"""API endpoint для серверного комментария к /weekly-report (TASK-LEAD-062).

Заменяет хранение в `localStorage` (только локально-в-браузере) на серверную
запись — менеджер пишет комментарий, РОП открывает ту же неделю и видит.

Endpoints:
  GET  /api/weekly-report/comment?week_start=YYYY-MM-DD[&brand=Foo]  — read
  PUT  /api/weekly-report/comment                                     — upsert

RBAC:
  - manager пишет/читает комментарии для своих brand'ов (brand-scope check
    через `brand_assignments`). brand=NULL читает (РОП-комментарий),
    но не редактирует.
  - director / head_of_sales — пишут/читают для любого brand'а и для
    brand=NULL (overall).
  - bookkeeper — 403 (нет доступа к управленческим отчётам).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, User, WeeklyReportComment
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
)

router = APIRouter(prefix="/api/weekly-report", tags=["weekly-report"])


class CommentResponse(BaseModel):
    week_start: date
    brand: str | None
    comment: str
    author_user_id: int | None
    author_name: str | None
    updated_at: datetime | None


class CommentUpsert(BaseModel):
    week_start: date
    brand: str | None = None
    comment: str


async def _assert_brand_access(
    session: AsyncSession,
    user: CurrentUser,
    brand: str | None,
    *,
    write: bool,
) -> None:
    """Проверка что user'у разрешено читать/писать комментарий для этого brand.

    - bookkeeper → 403 всегда (нет доступа к /weekly-report).
    - director / head_of_sales → можно всё.
    - manager:
        - read: brand=NULL (overall РОП-комментарий) — можно читать.
                Per-brand — только свои brand_assignments.
        - write: per-brand — только свои brand_assignments. brand=NULL —
                запрещено (overall — для РОПа).
    """
    role = user.role
    if role == "bookkeeper":
        raise HTTPException(403, "bookkeeper has no access to weekly-report")
    if role in ("director", "head_of_sales"):
        return
    # manager:
    if brand is None:
        if write:
            raise HTTPException(
                403, "managers cannot edit the overall (brand=null) comment"
            )
        return
    # manager + per-brand: проверить assignment
    assigned = (
        await session.execute(
            select(BrandAssignment.brand).where(
                BrandAssignment.tenant_id == user.tenant_id,
                BrandAssignment.user_id == user.id,
                BrandAssignment.brand == brand,
            )
        )
    ).first()
    if not assigned:
        raise HTTPException(403, f"brand {brand!r} is not in your assignments")


@router.get("/comment", response_model=CommentResponse)
async def get_comment(
    week_start: date = Query(..., description="Понедельник недели (UTC)"),
    brand: str | None = Query(None, description="NULL = overall (РОП-scope)"),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> CommentResponse:
    await _assert_brand_access(session, user, brand, write=False)

    row = (
        await session.execute(
            select(WeeklyReportComment).where(
                WeeklyReportComment.tenant_id == user.tenant_id,
                WeeklyReportComment.week_start == week_start,
                # Сравнение с NULL через IS NOT DISTINCT FROM — иначе brand=None
                # не находит NULL-строку.
                WeeklyReportComment.brand.is_(None)
                if brand is None
                else WeeklyReportComment.brand == brand,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        return CommentResponse(
            week_start=week_start,
            brand=brand,
            comment="",
            author_user_id=None,
            author_name=None,
            updated_at=None,
        )

    author_name: str | None = None
    if row.author_user_id is not None:
        u = (
            await session.execute(select(User).where(User.id == row.author_user_id))
        ).scalar_one_or_none()
        if u:
            author_name = u.username

    return CommentResponse(
        week_start=row.week_start,
        brand=row.brand,
        comment=row.comment,
        author_user_id=row.author_user_id,
        author_name=author_name,
        updated_at=row.updated_at,
    )


@router.put("/comment", response_model=CommentResponse)
async def upsert_comment(
    body: CommentUpsert,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> CommentResponse:
    await _assert_brand_access(session, user, body.brand, write=True)

    now = datetime.now(timezone.utc)
    # PostgreSQL — UPSERT через ON CONFLICT. UNIQUE-индекс
    # uq_weekly_report_comment_tenant_brand_week использует COALESCE(brand,'__overall__'),
    # из-за этого `index_elements` не работает — используем `index_where`-стратегию
    # вручную через два прохода (SELECT + UPDATE/INSERT).
    existing = (
        await session.execute(
            select(WeeklyReportComment).where(
                WeeklyReportComment.tenant_id == user.tenant_id,
                WeeklyReportComment.week_start == body.week_start,
                WeeklyReportComment.brand.is_(None)
                if body.brand is None
                else WeeklyReportComment.brand == body.brand,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        new_row = WeeklyReportComment(
            tenant_id=user.tenant_id,
            brand=body.brand,
            week_start=body.week_start,
            comment=body.comment,
            author_user_id=user.id,
            updated_at=now,
        )
        session.add(new_row)
        await session.commit()
        await session.refresh(new_row)
        target = new_row
    else:
        existing.comment = body.comment
        existing.author_user_id = user.id
        existing.updated_at = now
        await session.commit()
        await session.refresh(existing)
        target = existing

    # Подтянуть имя автора для UI «обновлено N мин назад автором X».
    u = (
        await session.execute(select(User).where(User.id == target.author_user_id))
    ).scalar_one_or_none()
    author_name = u.username if u else None

    return CommentResponse(
        week_start=target.week_start,
        brand=target.brand,
        comment=target.comment,
        author_user_id=target.author_user_id,
        author_name=author_name,
        updated_at=target.updated_at,
    )
