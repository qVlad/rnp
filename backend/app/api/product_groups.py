"""Product groups — собрать SKU в логические группы с ответственным.

Группы используются для фильтра по дашборду / план-факту / юнит-эконоmika.
SKU может состоять в нескольких группах одновременно (M:M).
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Product,
    ProductGroup,
    ProductGroupAssignment,
)
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot

router = APIRouter(prefix="/api/product-groups", tags=["product-groups"])


# ── Schemas ──────────────────────────────────────────────────────────────


class GroupPayload(BaseModel):
    name: str
    manager_name: str | None = None
    color: str | None = None
    comment: str | None = None


class AssignPayload(BaseModel):
    nm_ids: list[int]


GROUP_FIELDS = ["id", "name", "manager_name", "color", "comment"]


# ── List + counts ────────────────────────────────────────────────────────


@router.get("")
async def list_groups(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """List all groups with member count."""
    rows = (
        await session.execute(
            select(
                ProductGroup,
                func.count(ProductGroupAssignment.nm_id).label("members_count"),
            )
            .outerjoin(
                ProductGroupAssignment,
                ProductGroupAssignment.group_id == ProductGroup.id,
            )
            .group_by(ProductGroup.id)
            .order_by(ProductGroup.name)
        )
    ).all()
    return {
        "items": [
            {
                "id": g.id,
                "name": g.name,
                "manager_name": g.manager_name,
                "color": g.color,
                "comment": g.comment,
                "members_count": int(cnt or 0),
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g, cnt in rows
        ]
    }


@router.get("/{group_id}/members")
async def list_members(
    group_id: int, session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    g = await session.get(ProductGroup, group_id)
    if not g:
        raise HTTPException(404, "group not found")
    rows = (
        await session.execute(
            select(
                ProductGroupAssignment.nm_id,
                Product.vendor_code,
                Product.brand,
                Product.subject,
                Product.is_archived,
            )
            .outerjoin(
                Product, Product.nm_id == ProductGroupAssignment.nm_id
            )
            .where(ProductGroupAssignment.group_id == group_id)
            .order_by(ProductGroupAssignment.nm_id)
        )
    ).all()
    return {
        "group": {
            "id": g.id,
            "name": g.name,
            "manager_name": g.manager_name,
        },
        "items": [
            {
                "nm_id": int(r.nm_id),
                "vendor_code": r.vendor_code,
                "brand": r.brand,
                "subject": r.subject,
                "is_archived": r.is_archived,
            }
            for r in rows
        ],
    }


# ── CRUD ─────────────────────────────────────────────────────────────────


@router.post("")
async def create_group(
    payload: GroupPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    existing = (
        await session.execute(select(ProductGroup).where(ProductGroup.name == name))
    ).scalars().first()
    if existing:
        raise HTTPException(400, f"group with name {name!r} already exists")
    g = ProductGroup(
        name=name,
        manager_name=payload.manager_name,
        color=payload.color,
        comment=payload.comment,
    )
    session.add(g)
    await session.flush()
    await audit_log(
        session,
        "product_groups",
        "create",
        entity_id=str(g.id),
        after=snapshot(g, GROUP_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"id": g.id, "status": "created"}


@router.put("/{group_id}")
async def update_group(
    group_id: int,
    payload: GroupPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    g = await session.get(ProductGroup, group_id)
    if not g:
        raise HTTPException(404, "group not found")
    before = snapshot(g, GROUP_FIELDS)
    g.name = payload.name.strip() or g.name
    g.manager_name = payload.manager_name
    g.color = payload.color
    g.comment = payload.comment
    await audit_log(
        session,
        "product_groups",
        "update",
        entity_id=str(g.id),
        before=before,
        after=snapshot(g, GROUP_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "updated"}


@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    g = await session.get(ProductGroup, group_id)
    if not g:
        raise HTTPException(404, "group not found")
    before = snapshot(g, GROUP_FIELDS)
    await session.delete(g)
    await audit_log(
        session,
        "product_groups",
        "delete",
        entity_id=str(group_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}


# ── Assignments ──────────────────────────────────────────────────────────


@router.post("/{group_id}/assign")
async def assign_skus(
    group_id: int,
    payload: AssignPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add SKUs to the group. Idempotent — already-assigned ids are skipped."""
    g = await session.get(ProductGroup, group_id)
    if not g:
        raise HTTPException(404, "group not found")

    nm_ids = sorted({int(n) for n in payload.nm_ids if n})
    if not nm_ids:
        return {"added": 0, "skipped": 0}

    # ensure products exist
    for nm in nm_ids:
        if not await session.get(Product, nm):
            session.add(Product(nm_id=nm))
    await session.flush()

    # current members
    existing = set(
        (
            await session.execute(
                select(ProductGroupAssignment.nm_id).where(
                    ProductGroupAssignment.group_id == group_id,
                    ProductGroupAssignment.nm_id.in_(nm_ids),
                )
            )
        ).scalars().all()
    )
    new_ids = [n for n in nm_ids if n not in existing]
    for n in new_ids:
        session.add(ProductGroupAssignment(group_id=group_id, nm_id=n))

    await audit_log(
        session,
        "product_group_assignments",
        "create",
        entity_id=str(group_id),
        after={"group_id": group_id, "added_nm_ids": new_ids},
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"added": len(new_ids), "skipped": len(existing)}


@router.post("/{group_id}/unassign")
async def unassign_skus(
    group_id: int,
    payload: AssignPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    g = await session.get(ProductGroup, group_id)
    if not g:
        raise HTTPException(404, "group not found")

    nm_ids = sorted({int(n) for n in payload.nm_ids if n})
    if not nm_ids:
        return {"removed": 0}

    res = await session.execute(
        delete(ProductGroupAssignment).where(
            ProductGroupAssignment.group_id == group_id,
            ProductGroupAssignment.nm_id.in_(nm_ids),
        )
    )
    removed = int(res.rowcount or 0)
    await audit_log(
        session,
        "product_group_assignments",
        "delete",
        entity_id=str(group_id),
        before={"group_id": group_id, "removed_nm_ids": nm_ids},
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"removed": removed}


# ── For other pages: «get group_id of nm_id» map ─────────────────────────


@router.get("/membership-map")
async def membership_map(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return {nm_id: [group_id, ...]} for client-side filtering."""
    rows = (
        await session.execute(
            select(
                ProductGroupAssignment.nm_id, ProductGroupAssignment.group_id
            )
        )
    ).all()
    out: dict[str, list[int]] = {}
    for r in rows:
        out.setdefault(str(int(r.nm_id)), []).append(int(r.group_id))
    return {"map": out}
