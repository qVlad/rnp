"""Чарджбэки / штрафы WB API.

См. spec: `agents/references/spec-chargebacks.md` (LEAD-005).

Все ручки за `require_module("chargebacks")` — модуль включается per-tenant.
Все мутации — `require_director_or_head`. Удаление НЕ предусмотрено (только
переход в статус `cancelled`).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BrandAssignment,
    Chargeback,
    ChargebackHistory,
    ClaimTemplate,
    Product,
    User,
)
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.chargebacks import (
    CATEGORY_LABELS,
    INCOME_CATEGORIES,
    STATUS_LABELS,
    TransitionError,
    sync_chargebacks,
    transition,
)
from app.services.feature_flags import require_module


# Roвутер БЕЗ default `require_director_or_head` — manager должен видеть
# свои бренды в read-endpoints. Мутации (transition, sync, update) защищены
# через per-endpoint `Depends(require_director_or_head)`.
router = APIRouter(
    prefix="/api/chargebacks",
    tags=["chargebacks"],
    dependencies=[
        Depends(require_module("chargebacks")),
    ],
)


def _apply_brand_filter(stmt, brands: set[str] | None):
    """Применяет фильтр по брендам через JOIN на products.

    `brands=None` → unrestricted (director / head_of_sales).
    `brands=set()` → пустой результат (manager без brand_assignments).
    `brands={...}` → только chargebacks где chargeback.nm_id есть в товарах
                     этих брендов.
    """
    if brands is None:
        return stmt
    if not brands:
        # Empty set — guaranteed no results
        return stmt.where(Chargeback.id < 0)
    nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
    return stmt.where(Chargeback.nm_id.in_(nm_filter))


def _serialize_chargeback(c: Chargeback) -> dict[str, Any]:
    return {
        "id": c.id,
        "rrd_id": c.rrd_id,
        "category": c.category,
        "category_label": CATEGORY_LABELS.get(c.category, c.category),
        "is_income": c.category in INCOME_CATEGORIES,
        "supplier_oper_name": c.supplier_oper_name,
        "amount_rub": float(c.amount_rub),
        "nm_id": c.nm_id,
        "status": c.status,
        "status_label": STATUS_LABELS.get(c.status, c.status),
        "operation_dt": c.operation_dt.isoformat() if c.operation_dt else None,
        "rr_dt": c.rr_dt.isoformat() if c.rr_dt else None,
        "comment": c.comment,
        "claim_text": c.claim_text,
        "claim_filed_at": c.claim_filed_at.isoformat() if c.claim_filed_at else None,
        "wb_response": c.wb_response,
        "wb_responded_at": c.wb_responded_at.isoformat() if c.wb_responded_at else None,
        "recovered_amount": float(c.recovered_amount) if c.recovered_amount else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "created_by": c.created_by,
        "updated_by": c.updated_by,
    }


@router.get("")
async def list_chargebacks(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Список чарджбэков с фильтрами. Сортировка по operation_dt DESC.

    Manager видит только chargebacks по своим брендам (через join nm_id → products.brand).
    Director / head_of_sales — все.
    """
    stmt = _apply_brand_filter(select(Chargeback), brands)
    if status:
        stmt = stmt.where(Chargeback.status == status)
    if category:
        stmt = stmt.where(Chargeback.category == category)
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Chargeback.amount_rub >= Decimal(str(min_amount)))
    stmt = stmt.order_by(Chargeback.operation_dt.desc().nullslast(), Chargeback.id.desc())
    stmt = stmt.limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_chargeback(c) for c in rows], "limit": limit, "offset": offset}


async def _stats_by_manager(
    session: AsyncSession,
    date_from: date | None,
    date_to: date | None,
    brands: set[str] | None,
) -> dict[str, Any]:
    """LEAD-013: stats по менеджерам через JOIN chargebacks → products →
    brand_assignments → users. Если бренду назначены N менеджеров —
    chargeback попадает в N строк (это аналитика «у кого активность»).

    Чарджбэки nm_id IS NULL или brand без assignments → группа "unassigned".
    """
    # JOIN: c.nm_id → p.brand → ba.user_id → u.username
    base = (
        select(
            User.id.label("user_id"),
            User.username,
            User.full_name,
            Chargeback.status,
            func.count(Chargeback.id).label("cnt"),
            func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Chargeback.status == "resolved_recovered",
                            Chargeback.recovered_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("recovered"),
        )
        .join(Product, Product.nm_id == Chargeback.nm_id, isouter=True)
        .join(
            BrandAssignment,
            BrandAssignment.brand == Product.brand,
            isouter=True,
        )
        .join(User, User.id == BrandAssignment.user_id, isouter=True)
        .group_by(User.id, User.username, User.full_name, Chargeback.status)
    )
    if brands is None:
        stmt = base
    elif not brands:
        stmt = base.where(Chargeback.id < 0)
    else:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        stmt = base.where(Chargeback.nm_id.in_(nm_filter))
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    rows = (await session.execute(stmt)).all()

    by_user: dict[int | None, dict[str, Any]] = {}
    for r in rows:
        uid = r.user_id  # может быть None — unassigned
        u = by_user.setdefault(
            uid,
            {
                "user_id": uid,
                "username": r.username or "—",
                "full_name": r.full_name or ("Не назначен" if uid is None else r.username),
                "by_status": {},
                "total_count": 0,
                "total_amount": 0.0,
                "recovered_amount": 0.0,
            },
        )
        u["by_status"][r.status] = {
            "count": int(r.cnt or 0),
            "amount": float(r.total or 0),
        }
        u["total_count"] += int(r.cnt or 0)
        u["total_amount"] += float(r.total or 0)
        u["recovered_amount"] += float(r.recovered or 0)

    return {"group_by": "manager", "by_user": list(by_user.values())}


@router.get("/stats")
async def get_stats(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    group_by: str = Query(default="category"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Сводка чарджбэков. `group_by=category` (default) | `manager`.

    Manager видит свои бренды; director / head_of_sales — все.
    """
    if group_by == "manager":
        return await _stats_by_manager(session, date_from, date_to, brands)

    stmt = _apply_brand_filter(select(
        Chargeback.category,
        Chargeback.status,
        func.count(Chargeback.id).label("cnt"),
        func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
    ), brands).group_by(Chargeback.category, Chargeback.status)
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    rows = (await session.execute(stmt)).all()
    by_cat: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = by_cat.setdefault(
            r.category,
            {
                "category": r.category,
                "category_label": CATEGORY_LABELS.get(r.category, r.category),
                "is_income": r.category in INCOME_CATEGORIES,
                "by_status": {},
                "total_count": 0,
                "total_amount": 0.0,
            },
        )
        cat["by_status"][r.status] = {
            "count": int(r.cnt),
            "amount": float(r.total),
        }
        cat["total_count"] += int(r.cnt)
        cat["total_amount"] += float(r.total)
    return {"by_category": list(by_cat.values())}


@router.get("/{cid}")
async def get_chargeback(
    cid: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    stmt = _apply_brand_filter(select(Chargeback).where(Chargeback.id == cid), brands)
    c = (await session.execute(stmt)).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    # История переходов
    hist_rows = (
        await session.execute(
            select(ChargebackHistory)
            .where(ChargebackHistory.chargeback_id == cid)
            .order_by(ChargebackHistory.created_at.desc())
        )
    ).scalars().all()
    return {
        **_serialize_chargeback(c),
        "history": [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "comment": h.comment,
                "actor": h.actor,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hist_rows
        ],
    }


@router.put("/{cid}", dependencies=[Depends(require_director_or_head)])
async def update_chargeback(
    cid: int,
    comment: str | None = Body(default=None, embed=True),
    claim_text: str | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Обновить свободные поля — comment, claim_text. Не меняет статус."""
    c = (
        await session.execute(select(Chargeback).where(Chargeback.id == cid))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    if comment is not None:
        c.comment = comment
    if claim_text is not None:
        c.claim_text = claim_text
    c.updated_by = user.username
    await audit_log(
        session,
        "chargebacks",
        "update",
        entity_id=str(cid),
        after={"comment": comment, "claim_text": claim_text},
        actor=user.username,
    )
    await session.commit()
    return _serialize_chargeback(c)


@router.post("/{cid}/transition", dependencies=[Depends(require_director_or_head)])
async def transition_chargeback(
    cid: int,
    to_status: str = Body(..., embed=True),
    comment: str | None = Body(default=None, embed=True),
    wb_response: str | None = Body(default=None, embed=True),
    recovered_amount: float | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Перевод статуса с проверкой statemachine."""
    c = (
        await session.execute(select(Chargeback).where(Chargeback.id == cid))
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "chargeback not found")
    try:
        await transition(
            session,
            chargeback=c,
            to_status=to_status,
            actor=user.username,
            comment=comment,
            wb_response=wb_response,
            recovered_amount=Decimal(str(recovered_amount))
            if recovered_amount is not None
            else None,
        )
    except TransitionError as e:
        raise HTTPException(400, str(e))
    await audit_log(
        session,
        "chargebacks",
        "transition",
        entity_id=str(cid),
        after={
            "to_status": to_status,
            "comment": comment,
            "wb_response": wb_response,
            "recovered_amount": recovered_amount,
        },
        actor=user.username,
    )
    await session.commit()
    return _serialize_chargeback(c)


@router.post("/sync", dependencies=[Depends(require_director_or_head)])
async def trigger_sync(
    lookback_days: int = Body(default=60, embed=True, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Ручной запуск парсера — сканирует wb_report_detail за lookback_days
    и создаёт новые chargebacks. Идемпотентен (UNIQUE по rrd_id+category).
    """
    result = await sync_chargebacks(
        session,
        tenant_id=user.tenant_id,
        lookback_days=lookback_days,
    )
    await audit_log(
        session,
        "chargebacks",
        "sync",
        after=result,
        actor=user.username,
    )
    await session.commit()
    return result


@router.get("/meta/categories")
async def list_categories() -> dict[str, Any]:
    """Канонический список категорий + статусов для UI dropdown'ов."""
    return {
        "categories": [
            {
                "code": code,
                "label": label,
                "is_income": code in INCOME_CATEGORIES,
            }
            for code, label in CATEGORY_LABELS.items()
        ],
        "statuses": [{"code": code, "label": label} for code, label in STATUS_LABELS.items()],
    }


# ─── LEAD-014: claim_templates + XLSX-экспорт реестра ────────────────


@router.get("/templates")
async def list_claim_templates(
    category: str | None = Query(default=None),
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список шаблонов претензий. Опционально по категории."""
    stmt = select(ClaimTemplate)
    if category:
        stmt = stmt.where(ClaimTemplate.category == category)
    stmt = stmt.order_by(
        ClaimTemplate.category, ClaimTemplate.is_default.desc(), ClaimTemplate.name
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "category": t.category,
                "category_label": CATEGORY_LABELS.get(t.category, t.category),
                "name": t.name,
                "template_text": t.template_text,
                "is_default": t.is_default,
                "created_by": t.created_by,
            }
            for t in rows
        ]
    }


@router.post("/templates", dependencies=[Depends(require_director_or_head)])
async def create_claim_template(
    category: str = Body(..., embed=True),
    name: str = Body(..., embed=True),
    template_text: str = Body(..., embed=True),
    is_default: bool = Body(default=False, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Создать/обновить шаблон. UPSERT по (tenant, category, name)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if category not in CATEGORY_LABELS:
        raise HTTPException(400, f"unknown category: {category}")

    # Если is_default=true — снимаем дефолт со всех остальных в этой категории
    if is_default:
        from sqlalchemy import update
        await session.execute(
            update(ClaimTemplate)
            .where(
                ClaimTemplate.category == category,
                ClaimTemplate.is_default.is_(True),
            )
            .values(is_default=False)
        )

    stmt = pg_insert(ClaimTemplate).values(
        tenant_id=user.tenant_id,
        category=category,
        name=name,
        template_text=template_text,
        is_default=is_default,
        created_by=user.username,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "category", "name"],
        set_={
            "template_text": stmt.excluded.template_text,
            "is_default": stmt.excluded.is_default,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await audit_log(
        session,
        "claim_templates",
        "create",
        entity_id=f"{category}:{name}",
        after={"is_default": is_default},
        actor=user.username,
    )
    await session.commit()
    return {"category": category, "name": name}


@router.delete("/templates/{tid}", dependencies=[Depends(require_director_or_head)])
async def delete_claim_template(
    tid: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    t = (
        await session.execute(
            select(ClaimTemplate).where(ClaimTemplate.id == tid)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "template not found")
    await audit_log(
        session,
        "claim_templates",
        "delete",
        entity_id=f"{t.category}:{t.name}",
        actor=user.username,
    )
    await session.delete(t)
    await session.commit()
    return {"deleted": tid}


@router.get("/export.xlsx")
async def export_chargebacks_xlsx(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    """XLSX-экспорт реестра претензий с теми же фильтрами что и list endpoint.

    Бухгалтер забирает файл и подаёт в WB-поддержку через ЛК. Brand-filter
    применяется автоматически — manager получит только свои бренды.
    """
    from fastapi.responses import Response

    from app.services.chargebacks_export import build_chargebacks_xlsx

    stmt = _apply_brand_filter(select(Chargeback), brands)
    if status:
        stmt = stmt.where(Chargeback.status == status)
    if category:
        stmt = stmt.where(Chargeback.category == category)
    if date_from:
        stmt = stmt.where(Chargeback.operation_dt >= date_from)
    if date_to:
        stmt = stmt.where(Chargeback.operation_dt <= date_to)
    stmt = stmt.order_by(Chargeback.operation_dt.desc().nullslast()).limit(5000)
    rows = (await session.execute(stmt)).scalars().all()

    period_parts: list[str] = []
    if date_from:
        period_parts.append(f"с {date_from.isoformat()}")
    if date_to:
        period_parts.append(f"по {date_to.isoformat()}")
    period_label = " ".join(period_parts) if period_parts else "все даты"

    data = build_chargebacks_xlsx(rows, period_label=period_label)
    filename_dt = datetime.now().strftime("%Y%m%d")
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="chargebacks_{filename_dt}.xlsx"',
        },
    )
