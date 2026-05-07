"""Brand list + responsible-manager assignments.

The brand list is derived from `products.brand` — every distinct value seen in
WB cards/orders becomes a row here, joined to its `brand_assignments` row (if
any) and the assigned user's display name.

Routes:
    GET   /api/brands                  — list brands with nm_count and assignee
    PUT   /api/brands/{brand}/assignee — set or clear responsible user
                                          (director or head_of_sales)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, Product, User
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import require_director_or_head

router = APIRouter(
    prefix="/api/brands",
    tags=["brands"],
    dependencies=[Depends(require_director_or_head)],
)


class AssigneeIn(BaseModel):
    user_id: int | None = None  # null clears the assignment


def _ba_snap(row: BrandAssignment | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return snapshot(row, ["id", "brand", "user_id"])


@router.get("")
async def list_brands(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """All distinct WB brands with SKU count and current responsible user."""
    # 1) brand → nm_count from products
    rows = (
        await session.execute(
            select(
                Product.brand,
                func.count(Product.nm_id).label("nm_count"),
            )
            .where(Product.brand.is_not(None), Product.brand != "")
            .group_by(Product.brand)
            .order_by(Product.brand)
        )
    ).all()

    # 2) existing assignments → user (preload users for display name)
    assigns = {
        a.brand: a
        for a in (await session.execute(select(BrandAssignment))).scalars().all()
    }
    user_ids = {a.user_id for a in assigns.values() if a.user_id is not None}
    users: dict[int, User] = {}
    if user_ids:
        users = {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(user_ids)))
            )
            .scalars()
            .all()
        }

    items = []
    for r in rows:
        a = assigns.get(r.brand)
        u = users.get(a.user_id) if (a and a.user_id) else None
        items.append(
            {
                "brand": r.brand,
                "nm_count": int(r.nm_count or 0),
                "user_id": a.user_id if a else None,
                "username": u.username if u else None,
                "user_full_name": u.full_name if u else None,
                "updated_at": a.updated_at.isoformat() if a else None,
            }
        )
    return {"items": items}


@router.put("/{brand}/assignee")
async def set_assignee(
    brand: str,
    payload: AssigneeIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Validate the brand actually exists in the catalog (avoid orphan rows).
    has_brand = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.brand == brand)
        )
    ).scalar_one()
    if not has_brand:
        raise HTTPException(404, f"brand not found in products: {brand!r}")

    # Validate the user exists, is a manager, and is active (if not clearing).
    if payload.user_id is not None:
        user = await session.get(User, payload.user_id)
        if user is None:
            raise HTTPException(404, f"user {payload.user_id} not found")
        if not user.is_active:
            raise HTTPException(400, "user is disabled")
        if user.role != "manager":
            raise HTTPException(
                400, f"user role {user.role!r} cannot own brands; expected 'manager'"
            )

    existing = (
        await session.execute(
            select(BrandAssignment).where(BrandAssignment.brand == brand)
        )
    ).scalar_one_or_none()
    before = _ba_snap(existing)

    if existing is None:
        existing = BrandAssignment(brand=brand, user_id=payload.user_id)
        session.add(existing)
    else:
        existing.user_id = payload.user_id
        existing.updated_at = datetime.utcnow()
    await session.flush()

    after = _ba_snap(existing)
    op_kind = "create" if before is None else ("delete" if payload.user_id is None and before["user_id"] is not None else "update")
    await audit_log(
        session,
        "brand_assignments",
        op_kind,
        entity_id=str(existing.id),
        before=before,
        after=after,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"ok": True, "id": existing.id, "user_id": existing.user_id}
