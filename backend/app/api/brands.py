"""Brand list + responsible-manager assignments (N:M).

The brand list is derived from `products.brand` — every distinct value seen in
WB cards/orders becomes a row here, joined to all `brand_assignments` rows for
the brand (and the assigned users' display names).

Routes:
    GET    /api/brands                              — list brands with nm_count + all assignees
    POST   /api/brands/{brand}/assignees            — add a user to brand (idempotent)
    DELETE /api/brands/{brand}/assignees/{user_id}  — remove a user from brand
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, Product, User
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(
    prefix="/api/brands",
    tags=["brands"],
    dependencies=[Depends(require_director_or_head)],
)


class AssigneeIn(BaseModel):
    user_id: int


def _ba_snap(row: BrandAssignment) -> dict[str, Any]:
    return snapshot(row, ["id", "brand", "user_id"])


@router.get("")
async def list_brands(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    """All distinct WB brands with SKU count and current responsible users.

    Each brand may have zero, one, or many assignees. UI renders them as a
    list with × buttons + an "add user" dropdown.
    """
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

    # 2) all assignments (group later by brand)
    assigns = (
        await session.execute(
            select(BrandAssignment).where(BrandAssignment.user_id.is_not(None))
        )
    ).scalars().all()
    user_ids = {a.user_id for a in assigns if a.user_id is not None}
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
    assigns_by_brand: dict[str, list[BrandAssignment]] = {}
    for a in assigns:
        assigns_by_brand.setdefault(a.brand, []).append(a)

    items = []
    for r in rows:
        brand_assigns = assigns_by_brand.get(r.brand, [])
        assignees = []
        latest_updated_at: str | None = None
        for a in brand_assigns:
            u = users.get(a.user_id) if a.user_id else None
            if u is None:
                continue
            assignees.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "user_full_name": u.full_name,
                    "assignment_id": a.id,
                }
            )
            iso = a.updated_at.isoformat() if a.updated_at else None
            if iso and (latest_updated_at is None or iso > latest_updated_at):
                latest_updated_at = iso
        # Stable ordering by username for predictable UI
        assignees.sort(key=lambda x: (x["username"] or "").lower())
        items.append(
            {
                "brand": r.brand,
                "nm_count": int(r.nm_count or 0),
                "assignees": assignees,
                "updated_at": latest_updated_at,
            }
        )
    return {"items": items}


async def _validate_brand_and_user(
    session: AsyncSession, brand: str, user_id: int
) -> User:
    has_brand = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.brand == brand)
        )
    ).scalar_one()
    if not has_brand:
        raise HTTPException(404, f"brand not found in products: {brand!r}")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, f"user {user_id} not found")
    if not user.is_active:
        raise HTTPException(400, "user is disabled")
    if user.role != "manager":
        raise HTTPException(
            400, f"user role {user.role!r} cannot own brands; expected 'manager'"
        )
    return user


@router.post("/{brand}/assignees")
async def add_assignee(
    brand: str,
    payload: AssigneeIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Назначить менеджера на бренд. Идемпотентно: повторный POST с тем же
    user_id отдаёт существующую строку без ошибки."""
    await _validate_brand_and_user(session, brand, payload.user_id)

    existing = (
        await session.execute(
            select(BrandAssignment).where(
                BrandAssignment.brand == brand,
                BrandAssignment.user_id == payload.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "ok": True,
            "id": existing.id,
            "brand": brand,
            "user_id": payload.user_id,
            "created": False,
        }

    row = BrandAssignment(brand=brand, user_id=payload.user_id)
    session.add(row)
    await session.flush()
    await audit_log(
        session,
        "brand_assignments",
        "create",
        entity_id=str(row.id),
        after=_ba_snap(row),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {
        "ok": True,
        "id": row.id,
        "brand": brand,
        "user_id": payload.user_id,
        "created": True,
    }


@router.delete("/{brand}/assignees/{user_id}")
async def remove_assignee(
    brand: str,
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Снять менеджера с бренда. 404 если такого назначения не было."""
    row = (
        await session.execute(
            select(BrandAssignment).where(
                BrandAssignment.brand == brand,
                BrandAssignment.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "assignment not found")

    before = _ba_snap(row)
    row_id = row.id
    await session.delete(row)
    await audit_log(
        session,
        "brand_assignments",
        "delete",
        entity_id=str(row_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"ok": True}
