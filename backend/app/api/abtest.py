"""A/B-тесты — CRUD, действия, отчёты.

Endpoints (все под `/api/abtest`):

| Method | Path                                | Что                                             |
|--------|-------------------------------------|-------------------------------------------------|
| GET    | /                                   | список тестов (с фильтром archived)              |
| POST   | /                                   | создать новый тест (без фото — фото отдельно)    |
| GET    | /{id}                               | детали + варианты + последние ротации + alerts   |
| PUT    | /{id}                               | обновить настройки (только в статусе draft/paused)|
| DELETE | /{id}                               | удалить тест (draft/paused/archived)             |
| POST   | /{id}/start                         | запустить (draft → running)                      |
| POST   | /{id}/pause                         | приостановить (running → paused)                 |
| POST   | /{id}/resume                        | возобновить (paused → running)                   |
| POST   | /{id}/stop                          | остановить + восстановить исходное фото           |
| POST   | /{id}/archive                       | архивировать                                     |
| POST   | /{id}/unarchive                     | вернуть из архива                                |
| POST   | /{id}/apply-winner                  | body: {variant_id} — финал, completed+archived   |
| GET    | /{id}/result                        | значимость + победитель (live compute)            |
| GET    | /{id}/daily-stats                   | дневной агрегат для графика                       |
| GET    | /{id}/rotations                     | журнал ротаций                                    |
| GET    | /{id}/alerts                        | предупреждения                                    |
| POST   | /{id}/sync-now                      | принудительный stats sync                         |
| POST   | /{id}/budget-refresh                | принудительный budget poll + topup check          |
| POST   | /{id}/variants                      | добавить вариант                                  |
| DELETE | /{id}/variants/{vid}                | удалить вариант (draft/paused)                    |
| POST   | /{id}/variants/{vid}/eliminate      | отсеять (ручной)                                  |
| POST   | /{id}/variants/{vid}/un-eliminate   | вернуть в ротацию                                 |
| POST   | /alerts/{aid}/resolve               | отметить alert как resolved                       |

Photo uploads — в отдельном модуле `api/abtest_uploads.py` (multipart).

RBAC: get_db_tenant_scoped (все 3 роли). Manager автоматически ограничен по
`current_brands_filter()` на уровне продукта (через `products.brand`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AbTest,
    AbTestAlert,
    AbTestDailyStat,
    AbTestRotation,
    AbTestVariant,
    AbTestVariantPhoto,
    Product,
)
from app.services.abtest import (
    photo_storage,
    rotation as abtest_rotation,
    significance as ab_sig,
    stats as ab_stats,
)
from app.services.abtest.budget import poll_all_budgets_for_tenant
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.sync.tenants import tenant_sync_context

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/abtest", tags=["abtest"])


# ----------------------------------------------------------------------
# Pydantic schemas
# ----------------------------------------------------------------------


class TestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    nm_id: int
    trigger_mode: Literal["VIEWS", "TIME", "BUDGET"] = "VIEWS"
    trigger_value: int = Field(ge=1)
    traffic_source: Literal["ANY", "ADV_ONLY", "BOTH"] = "ANY"
    test_mode: Literal["PHOTO", "FUNNEL"] = "PHOTO"
    campaign_id: int | None = None
    campaign_type: int = 9
    min_sample_size: int = 1500
    confidence_level: float = 0.95
    keep_leaders_after_24h: bool = False
    budget_auto_topup: bool = False
    budget_min_threshold: int = 500
    budget_topup_amount: int = 1000
    budget_daily_limit: int = 10000
    # Минимум 2 варианта — пользователь даёт лейблы, фото добавляются отдельно.
    variant_labels: list[str] = Field(min_length=2, max_length=8)


class TestUpdate(BaseModel):
    name: str | None = None
    trigger_mode: Literal["VIEWS", "TIME", "BUDGET"] | None = None
    trigger_value: int | None = None
    min_sample_size: int | None = None
    confidence_level: float | None = None
    keep_leaders_after_24h: bool | None = None
    campaign_id: int | None = None
    campaign_type: int | None = None
    budget_auto_topup: bool | None = None
    budget_min_threshold: int | None = None
    budget_topup_amount: int | None = None
    budget_daily_limit: int | None = None


class VariantCreate(BaseModel):
    label: str = Field(min_length=1, max_length=8)


class ApplyWinner(BaseModel):
    variant_id: int


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


async def _check_nm_id_allowed(
    session: AsyncSession, nm_id: int, brands: set[str] | None
) -> Product:
    """Возвращает Product или 404. Manager без `brand_assignments` для брэнда — 403."""
    prod = await session.get(Product, nm_id)
    if prod is None:
        raise HTTPException(404, f"nm_id {nm_id} not found in products")
    if brands is not None and (prod.brand or "") not in brands:
        raise HTTPException(403, f"nm_id {nm_id} is not in your assigned brands")
    return prod


async def _check_test_access(
    session: AsyncSession, abtest_id: int, brands: set[str] | None
) -> AbTest:
    test = await session.get(AbTest, abtest_id)
    if test is None:
        raise HTTPException(404, "abtest not found")
    if brands is not None:
        # Manager видит тест только если его nm_id из его брендов.
        prod = await session.get(Product, test.nm_id)
        if prod is None or (prod.brand or "") not in brands:
            raise HTTPException(403, "test is not in your assigned brands")
    return test


def _serialize_test(t: AbTest) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "nm_id": t.nm_id,
        "status": t.status,
        "trigger_mode": t.trigger_mode,
        "trigger_value": t.trigger_value,
        "traffic_source": t.traffic_source,
        "test_mode": t.test_mode,
        "campaign_id": t.campaign_id,
        "campaign_type": t.campaign_type,
        "min_sample_size": t.min_sample_size,
        "confidence_level": float(t.confidence_level),
        "keep_leaders_after_24h": t.keep_leaders_after_24h,
        "leaders_culled_at": t.leaders_culled_at.isoformat() if t.leaders_culled_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ends_at": t.ends_at.isoformat() if t.ends_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "archived_at": t.archived_at.isoformat() if t.archived_at else None,
        "budget_auto_topup": t.budget_auto_topup,
        "budget_min_threshold": t.budget_min_threshold,
        "budget_topup_amount": t.budget_topup_amount,
        "budget_daily_limit": t.budget_daily_limit,
        "budget_topup_spent_today": t.budget_topup_spent_today,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _serialize_variant(v: AbTestVariant, photos: list[AbTestVariantPhoto]) -> dict[str, Any]:
    return {
        "id": v.id,
        "label": v.label,
        "eliminated_at": v.eliminated_at.isoformat() if v.eliminated_at else None,
        "photos": [
            {
                "id": p.id,
                "photo_order": p.photo_order,
                "content_type": p.content_type,
            }
            for p in photos
        ],
    }


def _serialize_rotation(r: AbTestRotation) -> dict[str, Any]:
    return {
        "id": r.id,
        "variant_id": r.variant_id,
        "applied_at": r.applied_at.isoformat(),
        "success": r.success,
        "error": r.error,
    }


def _serialize_alert(a: AbTestAlert) -> dict[str, Any]:
    return {
        "id": a.id,
        "message": a.message,
        "resolved": a.resolved,
        "created_at": a.created_at.isoformat(),
    }


# ----------------------------------------------------------------------
# Top-level CRUD
# ----------------------------------------------------------------------


@router.get("")
async def list_tests(
    include_archived: Annotated[bool, Query()] = False,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    stmt = select(AbTest).order_by(desc(AbTest.created_at))
    if not include_archived:
        stmt = stmt.where(AbTest.archived_at.is_(None))
    if status_filter:
        stmt = stmt.where(AbTest.status == status_filter)
    # Manager: только tests с nm_id из своих брендов.
    if brands is not None:
        stmt = stmt.where(
            AbTest.nm_id.in_(
                select(Product.nm_id).where(Product.brand.in_(brands))
            )
        )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_test(t) for t in rows]}


@router.post("")
async def create_test(
    payload: TestCreate,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    await _check_nm_id_allowed(session, payload.nm_id, brands)

    # Уникальность лейблов
    labels = [lbl.strip() for lbl in payload.variant_labels]
    if len(set(labels)) != len(labels):
        raise HTTPException(400, "variant labels must be unique")

    test = AbTest(
        name=payload.name,
        created_by_user_id=user.id,
        nm_id=payload.nm_id,
        status="draft",
        trigger_mode=payload.trigger_mode,
        trigger_value=payload.trigger_value,
        traffic_source=payload.traffic_source,
        test_mode=payload.test_mode,
        campaign_id=payload.campaign_id,
        campaign_type=payload.campaign_type,
        min_sample_size=payload.min_sample_size,
        confidence_level=payload.confidence_level,
        keep_leaders_after_24h=payload.keep_leaders_after_24h,
        budget_auto_topup=payload.budget_auto_topup,
        budget_min_threshold=payload.budget_min_threshold,
        budget_topup_amount=payload.budget_topup_amount,
        budget_daily_limit=payload.budget_daily_limit,
    )
    session.add(test)
    await session.flush()

    for label in labels:
        session.add(AbTestVariant(abtest_id=test.id, label=label))
    await session.commit()
    await session.refresh(test)

    return {"id": test.id, "test": _serialize_test(test)}


@router.get("/{abtest_id}")
async def get_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)

    variants = (
        await session.execute(
            select(AbTestVariant)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestVariant.label)
        )
    ).scalars().all()
    photos_by_variant: dict[int, list[AbTestVariantPhoto]] = {}
    if variants:
        ph_rows = (
            await session.execute(
                select(AbTestVariantPhoto)
                .where(AbTestVariantPhoto.variant_id.in_([v.id for v in variants]))
                .order_by(AbTestVariantPhoto.variant_id, AbTestVariantPhoto.photo_order)
            )
        ).scalars().all()
        for p in ph_rows:
            photos_by_variant.setdefault(p.variant_id, []).append(p)

    rotations = (
        await session.execute(
            select(AbTestRotation)
            .where(AbTestRotation.abtest_id == abtest_id)
            .order_by(desc(AbTestRotation.applied_at))
            .limit(20)
        )
    ).scalars().all()
    alerts = (
        await session.execute(
            select(AbTestAlert)
            .where(AbTestAlert.abtest_id == abtest_id, AbTestAlert.resolved.is_(False))
            .order_by(desc(AbTestAlert.created_at))
        )
    ).scalars().all()

    return {
        "test": _serialize_test(test),
        "variants": [
            _serialize_variant(v, photos_by_variant.get(v.id, [])) for v in variants
        ],
        "recent_rotations": [_serialize_rotation(r) for r in rotations],
        "alerts": [_serialize_alert(a) for a in alerts],
    }


@router.put("/{abtest_id}")
async def update_test(
    abtest_id: int,
    payload: TestUpdate,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status not in ("draft", "paused"):
        raise HTTPException(
            400, f"cannot update running/completed test (status={test.status})"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(test, field, value)
    await session.commit()
    return {"test": _serialize_test(test)}


@router.delete("/{abtest_id}")
async def delete_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status == "running":
        raise HTTPException(400, "stop or pause the running test first")
    # Удаление файлов — best-effort. CASCADE на БД делает остальное.
    await photo_storage.delete_abtest_photos(abtest_id)
    await session.delete(test)
    await session.commit()
    return {"status": "deleted"}


# ----------------------------------------------------------------------
# Lifecycle actions
# ----------------------------------------------------------------------


@router.post("/{abtest_id}/start")
async def start_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status not in ("draft", "paused"):
        raise HTTPException(400, f"cannot start from status {test.status}")
    # Все варианты должны иметь хотя бы 1 фото.
    variants = (
        await session.execute(
            select(AbTestVariant).where(AbTestVariant.abtest_id == abtest_id)
        )
    ).scalars().all()
    if len(variants) < 2:
        raise HTTPException(400, "test needs at least 2 variants")
    for v in variants:
        has_photo = (
            await session.scalar(
                select(exists().where(AbTestVariantPhoto.variant_id == v.id))
            )
        )
        if not has_photo:
            raise HTTPException(400, f"variant {v.label} has no photos")

    was_draft = test.status == "draft"
    test.status = "running"
    if test.started_at is None:
        test.started_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(test)

    # При первом старте — загружаем вариант A на WB (initial rotation).
    if was_draft:
        try:
            await abtest_rotation.apply_initial_variant(session, abtest_id)
            await session.commit()
        except Exception as e:
            log.warning("[abtest] initial rotation failed for %d: %s", abtest_id, e)

    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/pause")
async def pause_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status != "running":
        raise HTTPException(400, f"cannot pause from status {test.status}")
    test.status = "paused"
    await session.commit()
    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/resume")
async def resume_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status != "paused":
        raise HTTPException(400, f"cannot resume from status {test.status}")
    test.status = "running"
    await session.commit()
    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/stop")
async def stop_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status not in ("running", "paused"):
        raise HTTPException(400, f"cannot stop from status {test.status}")
    test.status = "cancelled"
    test.completed_at = datetime.now(timezone.utc)
    # TODO Phase 6: восстановление исходных фото через
    # `content_media.save_media_by_url(original_photos)`. Сейчас просто помечаем
    # cancelled — фото на WB остаются последнего применённого варианта.
    await session.commit()
    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/archive")
async def archive_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status == "running":
        raise HTTPException(400, "pause or stop the test before archiving")
    test.archived_at = datetime.now(timezone.utc)
    await session.commit()
    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/unarchive")
async def unarchive_test(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    test.archived_at = None
    await session.commit()
    return {"test": _serialize_test(test)}


@router.post("/{abtest_id}/apply-winner")
async def apply_winner(
    abtest_id: int,
    payload: ApplyWinner,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    try:
        ok = await abtest_rotation.apply_winner_variant(
            session, abtest_id, payload.variant_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await session.commit()
    if not ok:
        raise HTTPException(502, "WB upload failed — check alerts")
    return {"status": "applied"}


# ----------------------------------------------------------------------
# Variant management
# ----------------------------------------------------------------------


@router.post("/{abtest_id}/variants")
async def add_variant(
    abtest_id: int,
    payload: VariantCreate,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status not in ("draft", "paused"):
        raise HTTPException(400, "can add variants only in draft/paused")
    existing = (
        await session.execute(
            select(AbTestVariant.label).where(AbTestVariant.abtest_id == abtest_id)
        )
    ).scalars().all()
    if payload.label in existing:
        raise HTTPException(400, "label already exists in this test")
    v = AbTestVariant(abtest_id=abtest_id, label=payload.label)
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return {"variant": _serialize_variant(v, [])}


@router.delete("/{abtest_id}/variants/{variant_id}")
async def delete_variant(
    abtest_id: int,
    variant_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.status not in ("draft", "paused"):
        raise HTTPException(400, "can delete variants only in draft/paused")
    v = await session.get(AbTestVariant, variant_id)
    if v is None or v.abtest_id != abtest_id:
        raise HTTPException(404, "variant not found")
    # Удаляем фото-файлы вручную — CASCADE сносит строки в БД, но не диск.
    photos = (
        await session.execute(
            select(AbTestVariantPhoto).where(AbTestVariantPhoto.variant_id == variant_id)
        )
    ).scalars().all()
    for p in photos:
        await photo_storage.delete_photo_file(p.photo_path)
    await session.delete(v)
    await session.commit()
    return {"status": "deleted"}


@router.post("/{abtest_id}/variants/{variant_id}/eliminate")
async def eliminate_variant(
    abtest_id: int,
    variant_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    v = await session.get(AbTestVariant, variant_id)
    if v is None or v.abtest_id != abtest_id:
        raise HTTPException(404, "variant not found")
    if v.eliminated_at is not None:
        return {"variant_id": variant_id, "eliminated_at": v.eliminated_at.isoformat()}
    v.eliminated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"variant_id": variant_id, "eliminated_at": v.eliminated_at.isoformat()}


@router.post("/{abtest_id}/variants/{variant_id}/un-eliminate")
async def un_eliminate_variant(
    abtest_id: int,
    variant_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    v = await session.get(AbTestVariant, variant_id)
    if v is None or v.abtest_id != abtest_id:
        raise HTTPException(404, "variant not found")
    v.eliminated_at = None
    await session.commit()
    return {"variant_id": variant_id, "eliminated_at": None}


# ----------------------------------------------------------------------
# Reports + sync trigger
# ----------------------------------------------------------------------


@router.get("/{abtest_id}/result")
async def get_result(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    test = await _check_test_access(session, abtest_id, brands)
    variants = (
        await session.execute(
            select(AbTestVariant)
            .where(AbTestVariant.abtest_id == abtest_id)
            .order_by(AbTestVariant.label)
        )
    ).scalars().all()
    # Агрегат per-variant SUM по abtest_daily_stat (все источники).
    rows = (
        await session.execute(
            select(
                AbTestDailyStat.variant_id,
                func.coalesce(func.sum(AbTestDailyStat.impressions), 0),
                func.coalesce(func.sum(AbTestDailyStat.clicks), 0),
                func.coalesce(func.sum(AbTestDailyStat.cart_adds), 0),
                func.coalesce(func.sum(AbTestDailyStat.orders), 0),
                func.coalesce(func.sum(AbTestDailyStat.buyouts), 0),
            )
            .where(AbTestDailyStat.variant_id.in_([v.id for v in variants]))
            .group_by(AbTestDailyStat.variant_id)
        )
    ).all()
    agg = {int(r[0]): (int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5])) for r in rows}

    vs: list[ab_sig.VariantStats] = []
    for v in variants:
        imp, cl, ca, orders, buyouts = agg.get(v.id, (0, 0, 0, 0, 0))
        vs.append(
            ab_sig.VariantStats(
                variant_id=v.id,
                label=v.label,
                impressions=imp,
                clicks=cl,
                cart_adds=ca,
                orders=orders,
                buyouts=buyouts or None,
            )
        )

    # top_metric/top_denom — по wbab change_logic (см. significance.py docstring).
    if test.test_mode == "FUNNEL":
        top_metric: ab_sig.TopMetric = "cartAdds"
        top_denom: ab_sig.TopDenom = (
            "clicks" if test.traffic_source == "ADV_ONLY" else "impressions"
        )
    else:
        top_metric = "clicks"
        top_denom = "impressions"

    rep = ab_sig.compute_significance(
        vs,
        min_sample_size=test.min_sample_size,
        alpha=1 - float(test.confidence_level),
        top_metric=top_metric,
        top_denom=top_denom,
    )

    return {
        "top_metric": top_metric,
        "top_denom": top_denom,
        "alpha": 1 - float(test.confidence_level),
        "variants": [
            {
                "variant_id": v.variant_id,
                "label": v.label,
                "impressions": v.impressions,
                "clicks": v.clicks,
                "cart_adds": v.cart_adds,
                "orders": v.orders,
                "buyouts": v.buyouts,
            }
            for v in vs
        ],
        "ctr": {
            str(k): {"rate": v.rate, "ci_low": v.ci.lower, "ci_high": v.ci.upper}
            for k, v in rep.ctr.items()
        },
        "cr": {
            str(k): {"rate": v.rate, "ci_low": v.ci.lower, "ci_high": v.ci.upper}
            for k, v in rep.cr.items()
        },
        "pairwise": [
            {
                "a_id": p.a_id,
                "b_id": p.b_id,
                "a_label": p.a_label,
                "b_label": p.b_label,
                "ctr_p_value": p.ctr_test.p_value,
                "ctr_significant": p.ctr_test.significant,
                "cr_p_value": p.cr_test.p_value,
                "cr_significant": p.cr_test.significant,
            }
            for p in rep.pairwise
        ],
        "ctr_winner": (
            {"variant_id": rep.ctr_winner.variant_id, "label": rep.ctr_winner.label}
            if rep.ctr_winner
            else None
        ),
        "cr_winner": (
            {"variant_id": rep.cr_winner.variant_id, "label": rep.cr_winner.label}
            if rep.cr_winner
            else None
        ),
        "sample_progress": [
            {
                "variant_id": s.variant_id,
                "label": s.label,
                "current": s.current,
                "target": s.target,
                "pct": s.pct,
            }
            for s in rep.sample_progress
        ],
    }


@router.get("/{abtest_id}/daily-stats")
async def get_daily_stats(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    rows = await ab_stats.get_daily_stats_by_test(session, abtest_id)
    return {"items": rows}


@router.get("/{abtest_id}/rotations")
async def get_rotations(
    abtest_id: int,
    limit: Annotated[int, Query(le=500)] = 100,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    rows = (
        await session.execute(
            select(AbTestRotation)
            .where(AbTestRotation.abtest_id == abtest_id)
            .order_by(desc(AbTestRotation.applied_at))
            .limit(limit)
        )
    ).scalars().all()
    return {"items": [_serialize_rotation(r) for r in rows]}


@router.get("/{abtest_id}/alerts")
async def get_alerts(
    abtest_id: int,
    include_resolved: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    await _check_test_access(session, abtest_id, brands)
    stmt = (
        select(AbTestAlert)
        .where(AbTestAlert.abtest_id == abtest_id)
        .order_by(desc(AbTestAlert.created_at))
    )
    if not include_resolved:
        stmt = stmt.where(AbTestAlert.resolved.is_(False))
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_serialize_alert(a) for a in rows]}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    a = await session.get(AbTestAlert, alert_id)
    if a is None:
        raise HTTPException(404, "alert not found")
    await _check_test_access(session, a.abtest_id, brands)
    a.resolved = True
    await session.commit()
    return {"status": "resolved"}


@router.post("/{abtest_id}/sync-now")
async def sync_now(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    test = await _check_test_access(session, abtest_id, brands)
    # Открываем отдельный контекст с WB-клиентом — `session` уже tenant-scoped,
    # но не имеет открытого WbApiClient.
    async with tenant_sync_context(test.tenant_id) as ctx:
        if ctx is None:
            raise HTTPException(400, "no WB token configured for this tenant")
        sync_session, wb = ctx
        # session из tenant_sync_context — отдельный; перезагружаем test.
        sync_test = await sync_session.get(AbTest, abtest_id)
        if sync_test is None:
            raise HTTPException(404, "abtest disappeared between checks")
        await ab_stats.sync_test_stats(sync_session, sync_test, wb, quick_sync=False)
    return {"status": "synced"}


@router.post("/{abtest_id}/budget-refresh")
async def budget_refresh(
    abtest_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    test = await _check_test_access(session, abtest_id, brands)
    if test.campaign_id is None:
        raise HTTPException(400, "test has no campaign_id")
    await poll_all_budgets_for_tenant(test.tenant_id)
    return {"status": "refreshed"}
