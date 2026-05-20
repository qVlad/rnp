"""API для модуля перераспределения остатков (LEAD-008).

См. spec: REDISTRIBUTION_PLAN.md + agents/references/market/top-features-2026-05-17.md.

Все ручки за `require_module("redistribution")` — модуль включается per-tenant.
Все мутации — `require_director_or_head`.

В v1 endpoints для:
  - GET /status — статус LK-сессии (подключена / истекла / нужен relogin)
  - POST /lk/connect — сохранить AuthorizeV3 token (юзер вставляет вручную из DevTools)
  - DELETE /lk — отвязать сессию
  - GET /recommendations — pending рекомендации с экономикой
  - POST /recommendations/{id}/approve — поставить в очередь tasks
  - POST /recommendations/{id}/dismiss — отклонить
  - GET /tasks — очередь задач + история
  - GET /roi — ROI-дашборд (агрегат по snapshots + текущий месяц)
  - POST /generate — ручной триггер генерации рекомендаций

POST shifts.create (фактическое бронирование в окне) — отложено до получения
HAR в момент создания заявки в LK.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BrandAssignment,
    Product,
    RedistributionRecommendation,
    RedistributionRoiSnapshot,
    RedistributionTask,
    User,
    WbLkSession,
)
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
    require_director_or_head,
)
from app.services.feature_flags import require_module
from app.services.redistribution.scheduler import next_window_at
from app.services.redistribution.session_store import (
    load_session,
    mark_needs_relogin,
    save_authorize_v3,
)


# Read-endpoints доступны manager'у (с brand-фильтром). Mutation-endpoints
# (lk/connect, approve/dismiss, generate, transition) защищены отдельно
# `Depends(require_director_or_head)`.
router = APIRouter(
    prefix="/api/redistribution",
    tags=["redistribution"],
    dependencies=[
        Depends(require_module("redistribution")),
    ],
)


def _apply_brand_filter_recs(stmt, brands: set[str] | None):
    """Brand-filter для RedistributionRecommendation через nm_id → products.brand."""
    if brands is None:
        return stmt
    if not brands:
        return stmt.where(RedistributionRecommendation.id < 0)
    nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
    return stmt.where(RedistributionRecommendation.nm_id.in_(nm_filter))


def _apply_brand_filter_tasks(stmt, brands: set[str] | None):
    """Brand-filter для RedistributionTask. Tasks не имеют nm_id напрямую —
    джоин через recommendation_id. Если recommendation удалена — task недоступен.
    """
    if brands is None:
        return stmt
    if not brands:
        return stmt.where(RedistributionTask.id < 0)
    nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
    rec_filter = select(RedistributionRecommendation.id).where(
        RedistributionRecommendation.nm_id.in_(nm_filter)
    )
    return stmt.where(RedistributionTask.recommendation_id.in_(rec_filter))


@router.get("/status")
async def get_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сводный статус: подключена ли LK-сессия, валиден ли токен, когда
    ближайшее окно бронирования."""
    s = await load_session(session, user.tenant_id)
    if s is None:
        return {
            "lk_connected": False,
            "lk_needs_relogin": False,
            "next_window_at": next_window_at().isoformat(),
        }
    now = datetime.now(timezone.utc)
    authorize_expired = (s.authorize_v3_exp is None) or (s.authorize_v3_exp < now)
    lk_seconds_left = None
    if s.wb_seller_lk_exp:
        lk_seconds_left = int((s.wb_seller_lk_exp - now).total_seconds())
    return {
        "lk_connected": not s.needs_relogin and not authorize_expired,
        "lk_needs_relogin": s.needs_relogin,
        "authorize_v3_expires_at": s.authorize_v3_exp.isoformat()
        if s.authorize_v3_exp
        else None,
        "wb_seller_lk_expires_at": s.wb_seller_lk_exp.isoformat()
        if s.wb_seller_lk_exp
        else None,
        "wb_seller_lk_seconds_left": lk_seconds_left,
        "phone_last4": s.phone_last4,
        "supplier_fid": s.supplier_fid,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
        "root_version": s.root_version,
        "next_window_at": next_window_at().isoformat(),
    }


@router.post("/lk/connect", dependencies=[Depends(require_director)])
async def connect_lk(
    authorize_v3: str = Body(..., embed=True),
    wb_seller_lk: str | None = Body(default=None, embed=True),
    user_agent: str | None = Body(default=None, embed=True),
    root_version: str | None = Body(default=None, embed=True),
    phone_last4: str | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сохранить долгоживущий AuthorizeV3 (юзер вставляет из DevTools после
    логина в seller.wildberries.ru). Только director.

    Опционально `wb_seller_lk` — короткий 5-мин токен. До закрытия
    TASK-LEAD-019 (auto-refresh) пользователь должен передавать его
    вручную перед каждым окном бронирования.
    """
    # Проверяем существование до save_authorize_v3, чтобы понять
    # create vs update для audit_log (после flush'а ленивая загрузка
    # server_default колонок ломает async greenlet).
    existing = await load_session(session, user.tenant_id)
    audit_action = "update" if existing else "create"
    try:
        s = await save_authorize_v3(
            session,
            tenant_id=user.tenant_id,
            authorize_v3=authorize_v3,
            wb_seller_lk=wb_seller_lk,
            user_agent=user_agent,
            root_version=root_version,
            phone_last4=phone_last4,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit_log(
        session,
        "wb_lk_sessions",
        audit_action,
        entity_id=str(user.tenant_id),
        after={
            "phone_last4": phone_last4,
            "root_version": root_version,
            "wb_seller_lk_supplied": bool(wb_seller_lk),
        },
        actor=user.username,
    )
    await session.commit()
    return {
        "lk_connected": True,
        "authorize_v3_expires_at": s.authorize_v3_exp.isoformat()
        if s.authorize_v3_exp
        else None,
        "wb_seller_lk_expires_at": s.wb_seller_lk_exp.isoformat()
        if s.wb_seller_lk_exp
        else None,
    }


@router.delete("/lk", dependencies=[Depends(require_director)])
async def disconnect_lk(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Отвязать LK-сессию. После этого все redistribution-задачи будут skip'ать."""
    s = await load_session(session, user.tenant_id)
    if s is None:
        raise HTTPException(404, "no LK session")
    await session.delete(s)
    await audit_log(
        session,
        "wb_lk_sessions",
        "delete",
        entity_id=str(user.tenant_id),
        actor=user.username,
    )
    await session.commit()
    return {"deleted": True}


def _serialize_rec(r: RedistributionRecommendation) -> dict[str, Any]:
    return {
        "id": r.id,
        "nm_id": r.nm_id,
        "chrt_id": r.chrt_id,
        "from_office_name": r.from_office_name,
        "to_office_name": r.to_office_name,
        "qty": r.qty,
        "expected_logistics_saving_rub": float(r.expected_logistics_saving_rub or 0),
        "expected_revenue_uplift_rub": float(r.expected_revenue_uplift_rub or 0),
        "cost_share_rub": float(r.cost_share_rub or 0),
        "net_benefit_rub": float(r.net_benefit_rub or 0),
        "payback_days": float(r.payback_days) if r.payback_days else None,
        "demand_14d_at_target": r.demand_14d_at_target,
        "current_stock_at_target": r.current_stock_at_target,
        "current_stock_at_source": r.current_stock_at_source,
        "status": r.status,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
    }


@router.get("/recommendations")
async def list_recommendations(
    status: str | None = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Топ-N рекомендаций. По умолчанию status='pending'.

    Manager видит рекомендации только по своим брендам.
    """
    stmt = _apply_brand_filter_recs(select(RedistributionRecommendation), brands)
    if status:
        stmt = stmt.where(RedistributionRecommendation.status == status)
    else:
        stmt = stmt.where(RedistributionRecommendation.status == "pending")
    stmt = stmt.order_by(
        RedistributionRecommendation.net_benefit_rub.desc().nullslast()
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_rec(r) for r in rows]}


@router.post("/recommendations/{rid}/approve", dependencies=[Depends(require_director_or_head)])
async def approve_recommendation(
    rid: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Перевести рекомендацию в очередь tasks под ближайшее окно."""
    r = (
        await session.execute(
            select(RedistributionRecommendation).where(
                RedistributionRecommendation.id == rid
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "recommendation not found")
    if r.status != "pending":
        raise HTTPException(
            400, f"only pending recs can be approved (current: {r.status})"
        )

    r.status = "queued"
    window = next_window_at()
    task = RedistributionTask(
        tenant_id=user.tenant_id,
        recommendation_id=r.id,
        target_window_at=window,
        chrt_id=r.chrt_id,
        from_office_id=r.from_office_id,
        from_office_name=r.from_office_name,
        to_office_id=r.to_office_id or 0,
        to_office_name=r.to_office_name,
        qty=r.qty,
        priority=int(r.net_benefit_rub or 0),
        status="queued",
    )
    session.add(task)
    await audit_log(
        session,
        "redistribution_tasks",
        "create",
        entity_id=f"rec={rid}",
        after={"target_window_at": window.isoformat(), "qty": r.qty},
        actor=user.username,
    )
    await session.commit()
    return {"task_window_at": window.isoformat(), "task_id": task.id}


@router.post("/recommendations/{rid}/dismiss", dependencies=[Depends(require_director_or_head)])
async def dismiss_recommendation(
    rid: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    r = (
        await session.execute(
            select(RedistributionRecommendation).where(
                RedistributionRecommendation.id == rid
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "recommendation not found")
    r.status = "dismissed"
    await audit_log(
        session,
        "redistribution_recommendations",
        "update",
        entity_id=str(rid),
        after={"status": "dismissed"},
        actor=user.username,
    )
    await session.commit()
    return {"id": rid, "status": "dismissed"}


def _serialize_task(t: RedistributionTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "target_window_at": t.target_window_at.isoformat() if t.target_window_at else None,
        "chrt_id": t.chrt_id,
        "from_office_name": t.from_office_name,
        "to_office_name": t.to_office_name,
        "qty": t.qty,
        "status": t.status,
        "attempt_count": t.attempt_count,
        "last_attempt_at": t.last_attempt_at.isoformat() if t.last_attempt_at else None,
        "last_status_code": t.last_status_code,
        "last_response": t.last_response,
        "accepted_at": t.accepted_at.isoformat() if t.accepted_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Очередь tasks + история. Manager видит свои бренды (через recommendation_id join)."""
    stmt = _apply_brand_filter_tasks(select(RedistributionTask), brands)
    if status:
        stmt = stmt.where(RedistributionTask.status == status)
    stmt = stmt.order_by(RedistributionTask.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_task(t) for t in rows]}


@router.post("/tasks/{tid}/retry", dependencies=[Depends(require_director_or_head)])
async def retry_task(
    tid: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Вернуть failed task в очередь (сбрасывает attempt_count). После
    MAX_RETRY_ATTEMPTS execute_window помечает task permanent-failed; эта
    ручка даёт перезапустить вручную после устранения причины (расширение
    переподключено, LK relogin, и т.п.).

    Также сбрасывает связанную recommendation в 'queued' если она была
    'failed' — иначе by-manager analytics не подхватит retry.
    """
    t = (
        await session.execute(
            select(RedistributionTask).where(RedistributionTask.id == tid)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "task not found")
    if t.status != "failed":
        raise HTTPException(
            400, f"only failed tasks can be retried (current: {t.status})"
        )
    t.status = "queued"
    t.attempt_count = 0
    t.last_attempt_at = None
    t.last_status_code = None
    t.last_response = "manual retry"
    if t.recommendation_id:
        from sqlalchemy import update as sql_update

        await session.execute(
            sql_update(RedistributionRecommendation)
            .where(
                RedistributionRecommendation.id == t.recommendation_id,
                RedistributionRecommendation.status == "failed",
            )
            .values(status="queued")
        )
    await audit_log(
        session,
        "redistribution_tasks",
        "update",
        entity_id=str(tid),
        after={"status": "queued", "attempt_count": 0},
        actor=user.username,
    )
    await session.commit()
    return {"id": tid, "status": "queued"}


@router.get("/by-manager")
async def get_by_manager(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """LEAD-013: redistribution analytics per-manager — для ROP-view.

    Считаем по `redistribution_recommendations` (там есть nm_id):
      - count(*) + sum(net_benefit) по `recommendations.status` (pending /
        approved / queued / executed / failed)
    Группируем по user через JOIN nm_id → products.brand → brand_assignments.
    """
    base = (
        select(
            User.id.label("user_id"),
            User.username,
            User.full_name,
            RedistributionRecommendation.status,
            func.count(RedistributionRecommendation.id).label("cnt"),
            func.coalesce(
                func.sum(RedistributionRecommendation.net_benefit_rub), 0
            ).label("net_benefit"),
            func.coalesce(
                func.sum(RedistributionRecommendation.expected_logistics_saving_rub),
                0,
            ).label("saving"),
        )
        .join(
            Product,
            Product.nm_id == RedistributionRecommendation.nm_id,
            isouter=True,
        )
        .join(
            BrandAssignment,
            BrandAssignment.brand == Product.brand,
            isouter=True,
        )
        .join(User, User.id == BrandAssignment.user_id, isouter=True)
        .group_by(
            User.id,
            User.username,
            User.full_name,
            RedistributionRecommendation.status,
        )
    )
    if brands is None:
        stmt = base
    elif not brands:
        stmt = base.where(RedistributionRecommendation.id < 0)
    else:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        stmt = base.where(RedistributionRecommendation.nm_id.in_(nm_filter))
    if date_from:
        stmt = stmt.where(
            func.date(RedistributionRecommendation.generated_at) >= date_from
        )
    if date_to:
        stmt = stmt.where(
            func.date(RedistributionRecommendation.generated_at) <= date_to
        )

    rows = (await session.execute(stmt)).all()
    by_user: dict[int | None, dict[str, Any]] = {}
    for r in rows:
        uid = r.user_id
        u = by_user.setdefault(
            uid,
            {
                "user_id": uid,
                "username": r.username or "—",
                "full_name": r.full_name or ("Не назначен" if uid is None else r.username),
                "by_status": {},
                "total_count": 0,
                "total_net_benefit": 0.0,
                "total_saving": 0.0,
            },
        )
        u["by_status"][r.status] = {
            "count": int(r.cnt or 0),
            "net_benefit": float(r.net_benefit or 0),
        }
        u["total_count"] += int(r.cnt or 0)
        u["total_net_benefit"] += float(r.net_benefit or 0)
        u["total_saving"] += float(r.saving or 0)
    return {"by_user": list(by_user.values())}


@router.get("/roi")
async def get_roi(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """ROI-дашборд: суммы за период из snapshots + сводка по tasks."""
    stmt = select(
        func.coalesce(func.sum(RedistributionRoiSnapshot.revenue_total_rub), 0).label("revenue"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.redistribution_fee_rub), 0).label("fee"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.logistics_saving_rub), 0).label("saving"),
        func.coalesce(func.avg(RedistributionRoiSnapshot.il_avg_pct), 0).label("il_avg"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.successful_tasks_count), 0).label("ok"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.failed_tasks_count), 0).label("fail"),
    )
    if date_from:
        stmt = stmt.where(RedistributionRoiSnapshot.snapshot_date >= date_from)
    if date_to:
        stmt = stmt.where(RedistributionRoiSnapshot.snapshot_date <= date_to)
    row = (await session.execute(stmt)).one()

    revenue = float(row.revenue or 0)
    fee = float(row.fee or 0)
    saving = float(row.saving or 0)
    roi_pct = None
    if fee > 0:
        roi_pct = round(saving / fee * 100, 1)
    return {
        "period": {
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
        },
        "revenue_rub": revenue,
        "redistribution_fee_rub": fee,
        "logistics_saving_rub": saving,
        "roi_pct": roi_pct,
        "il_avg_pct": float(row.il_avg or 0),
        "successful_tasks_count": int(row.ok or 0),
        "failed_tasks_count": int(row.fail or 0),
    }


@router.post("/generate", dependencies=[Depends(require_director_or_head)])
async def trigger_generate(
    limit: int = 30,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Ручной триггер генерации рекомендаций.

    После LEAD-020 рекомендации генерятся **через Chrome-extension proxy**
    (расширение должно быть подключено + открыта вкладка seller.wildberries.ru).
    Каждый nm_id → один stocks job в queue, extension polls раз в 30 сек.
    Для batch=10 SKU расширение обработает за один цикл ~5-10 сек, для
    larger limit — несколько циклов.

    Параметр `limit` (default 30) ограничивает кол-во SKU. Для smoke-теста
    рекомендую 5-10 чтобы не ждать долго.
    """
    from app.db.models import Product, WbSale
    from app.services.redistribution.recommender import build_recommendations
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        await session.execute(
            select(Product.nm_id)
            .join(WbSale, WbSale.nm_id == Product.nm_id)
            .where(WbSale.sale_dt >= since, WbSale.is_return.is_(False))
            .where(Product.is_archived.is_(False))
            .group_by(Product.nm_id)
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    nm_ids = [int(r[0]) for r in rows]
    if not nm_ids:
        return {"created": 0, "message": "no active SKU"}

    # Удаляем старые pending-рекомендации перед генерацией свежих — иначе
    # повторный клик «Пересчитать» создаёт дубли (один и тот же candidate
    # × количество запусков). Approved/dismissed — оставляем как историю.
    from sqlalchemy import delete as sql_delete

    await session.execute(
        sql_delete(RedistributionRecommendation).where(
            RedistributionRecommendation.status == "pending",
        )
    )

    recs = await build_recommendations(
        session, tenant_id=user.tenant_id, nm_ids=nm_ids
    )
    for r in recs:
        session.add(
            RedistributionRecommendation(
                tenant_id=user.tenant_id,
                nm_id=r.nm_id,
                chrt_id=r.chrt_id,
                from_office_id=r.from_office_id or None,
                from_office_name=r.from_office_name,
                to_office_id=r.to_office_id or None,
                to_office_name=r.to_office_name,
                qty=r.qty,
                expected_logistics_saving_rub=r.econ.expected_logistics_saving_rub,
                expected_revenue_uplift_rub=r.econ.expected_revenue_uplift_rub,
                cost_share_rub=r.econ.cost_share_rub,
                net_benefit_rub=r.econ.net_benefit_rub,
                payback_days=r.econ.payback_days,
                demand_14d_at_target=r.demand_14d_at_target,
                current_stock_at_target=r.current_stock_at_target,
                current_stock_at_source=r.current_stock_at_source,
                transit_days_estimated=r.transit_days_estimated,
                status="pending",
            )
        )
    await audit_log(
        session,
        "redistribution_recommendations",
        "create",
        entity_id="bulk",
        after={"count": len(recs)},
        actor=user.username,
    )
    await session.commit()
    return {"created": len(recs)}
