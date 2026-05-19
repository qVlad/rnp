"""Endpoints для Chrome-расширения (companion-MV3, см. /extension/).

Расширение работает в браузере пользователя:
  • content script на seller.wildberries.ru — launcher + badge активного теста
  • content script на www.wildberries.ru — трекинг позиций в каталоге
  • service worker — periodic poll новых winner-событий, notifications
  • popup/options — React UI

Backend контракт (читать в паре с extension/src/lib/wbab-api.ts):

| Method | Path                              | Что                                          |
|--------|-----------------------------------|----------------------------------------------|
| GET    | /api/extension/tests/active       | список running тестов (опц. фильтр nmId)     |
| GET    | /api/extension/winners/since      | новые winner-события после cursor (unix ms)  |
| POST   | /api/extension/positions          | позиции карточек из выдачи WB (трекинг)      |
| POST   | /api/extension/wb-token/save      | auto-token save (deprecated, stub)           |
| GET    | /api/extension/wb-token/status    | состояние WB-токена tenant'а                 |

**Auth**: `Authorization: Bearer <jwt>` — JWT тот же, что в cookie
`rnp_session` (см. services/auth.create_session_token). MVP — юзер копирует
JWT из cookie в options расширения вручную. Постепенно сделаем отдельный
long-lived API-token с привязкой к user_id (отдельная задача).

**Tenant scoping**: все запросы фильтруются по `tenant_id` из JWT.
Manager-роли видят только тесты на своих брендах (через `current_brands_filter`).

**Why a separate router (vs reusing /api/abtest)?**
  • Стабильный контракт под расширение — менять схемы /api/abtest можно без
    оглядки на старые версии extension в браузерах пользователей.
  • Аутентификация Bearer (header), а не cookie — extension не делит cookie-
    jar с UI и шлёт токен явно.
  • Минимальный surface — только то, что нужно SW и content scripts.
    Полный CRUD A/B-тестов остаётся в /api/abtest для основного UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AbTest,
    AbTestResult,
    AbTestVariant,
    Product,
    Tenant,
    User,
)
from app.db.session import get_db
from app.services.auth import CurrentUser, decode_session_token
from app.services.tenant_context import set_tenant

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extension", tags=["extension"])


# ─────────────────────────────────────────────────────────────────────────
# Bearer-token auth
# ─────────────────────────────────────────────────────────────────────────


async def _user_from_bearer(
    request: Request,
    session: AsyncSession,
    authorization: str | None,
) -> CurrentUser:
    """Resolve user from `Authorization: Bearer <jwt>` header.

    Mirrors `services.auth.get_current_user` but reads the token from the
    HTTP header instead of the session cookie. Raises 401 on any failure.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(401, "bearer token invalid or expired")
    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(401, "bearer payload malformed") from e
    user = await session.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(401, "user not found or disabled")
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
        tenant_id=int(user.tenant_id),
    )


async def get_extension_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency: resolve current user + scope session to tenant."""
    user = await _user_from_bearer(request, session, authorization)
    set_tenant(session, user.tenant_id)
    return user


# ─────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────


class ActiveTestOut(BaseModel):
    """Должен совпадать с типом ActiveTest в extension/src/lib/types.ts."""

    id: str
    name: str
    status: str
    nmId: int
    activeVariantLabel: str
    nextRotationAt: str | None
    scenario: str
    winnerVariantLabel: str | None
    sampleProgressPct: int


class WinnerEventOut(BaseModel):
    testId: str
    testName: str
    nmId: int
    winnerVariantLabel: str
    detectedAt: str


class PositionsPayload(BaseModel):
    nmId: int
    query: str
    position: int
    page: int
    collectedAt: str


class WbTokenSavePayload(BaseModel):
    jwt: str = Field(min_length=1)
    expiresAt: int | None = None


class WbTokenStatusOut(BaseModel):
    hasToken: bool
    source: str | None  # "manual" | "auto" | null
    expiresAt: str | None
    needsRefresh: bool


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _scenario_for(test: AbTest) -> str:
    """Maps AbTest.traffic_source + test_mode to legacy ActiveTest.scenario.

    The extension currently understands these labels (см. types.ts):
      ADV_PHOTO | ANY_FUNNEL | BOTH_FUNNEL | ADV_FUNNEL | LEGACY
    """
    src = test.traffic_source
    mode = test.test_mode
    if src == "ADV_ONLY" and mode == "PHOTO":
        return "ADV_PHOTO"
    if src == "ADV_ONLY" and mode == "FUNNEL":
        return "ADV_FUNNEL"
    if src == "BOTH" and mode == "FUNNEL":
        return "BOTH_FUNNEL"
    if src == "ANY" and mode == "FUNNEL":
        return "ANY_FUNNEL"
    return "LEGACY"


async def _resolve_active_variant_label(
    session: AsyncSession, abtest_id: int
) -> str:
    """Какой вариант сейчас «активен» на витрине.

    TODO: для PHOTO-тестов с TIME-триггером — это вариант последней успешной
    ротации (см. AbTestRotation). Сейчас возвращаем label первого
    not-eliminated варианта по порядку (A < B < C < D). Достаточно для UI
    badge'а, но для точного отображения нужен last-rotation-resolver.
    """
    row = (
        await session.execute(
            select(AbTestVariant.label)
            .where(
                AbTestVariant.abtest_id == abtest_id,
                AbTestVariant.eliminated_at.is_(None),
            )
            .order_by(AbTestVariant.label)
            .limit(1)
        )
    ).scalar()
    return row or "A"


async def _winner_label_for(
    session: AsyncSession, abtest_id: int
) -> str | None:
    """Если по тесту уже есть applied winner — вернуть его label."""
    res = (
        await session.execute(
            select(AbTestVariant.label)
            .join(AbTestResult, AbTestResult.winner_variant_id == AbTestVariant.id)
            .where(AbTestResult.abtest_id == abtest_id)
            .limit(1)
        )
    ).scalar()
    return res


def _sample_progress_pct(test: AbTest) -> int:
    """Грубая оценка прогресса 0..100 для UI badge'а.

    TODO: пока возвращаем 0 — для точной оценки нужны live-stats из
    AbTestDailyStat / AbTestVariantPlatformSnap (по trigger_mode VIEWS/
    TIME/BUDGET агрегаты считаются по-разному). Сделать в отдельной фиче
    «прогресс выборки в badge'е».
    """
    return 0


def _serialize_active(
    test: AbTest, active_label: str, winner_label: str | None
) -> dict[str, Any]:
    return ActiveTestOut(
        id=str(test.id),
        name=test.name,
        status=test.status,
        nmId=test.nm_id,
        activeVariantLabel=active_label,
        # TODO: next_rotation_at — для TIME-триггера хранится в Celery beat;
        # для VIEWS/BUDGET вычисляется динамически. Сейчас null — extension
        # просто не показывает таймер.
        nextRotationAt=None,
        scenario=_scenario_for(test),
        winnerVariantLabel=winner_label,
        sampleProgressPct=_sample_progress_pct(test),
    ).model_dump()


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@router.get("/tests/active", response_model=list[ActiveTestOut])
async def list_active_tests(
    nmId: Annotated[int | None, Query()] = None,
    user: CurrentUser = Depends(get_extension_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Список running тестов tenant'а. Опционально фильтр по конкретному nmId.

    Manager-role: ограничение по своим брендам — через JOIN с products.brand
    и `current_brands_filter`. Сейчас в этом endpoint'е manager-фильтр
    реализован вручную (не reuse Depends, потому что сессия инициализируется
    под другой DI flow).
    """
    stmt = (
        select(AbTest)
        .where(AbTest.status == "running", AbTest.archived_at.is_(None))
        .order_by(desc(AbTest.created_at))
    )
    if nmId is not None:
        stmt = stmt.where(AbTest.nm_id == nmId)

    # Brand-filter для manager-role
    if not user.sees_all_brands:
        from app.db.models import BrandAssignment

        brands_stmt = select(BrandAssignment.brand).where(
            BrandAssignment.user_id == user.id,
            BrandAssignment.tenant_id == user.tenant_id,
        )
        brands = {b for b in (await session.execute(brands_stmt)).scalars().all() if b}
        if not brands:
            return []
        stmt = stmt.where(
            AbTest.nm_id.in_(
                select(Product.nm_id).where(Product.brand.in_(brands))
            )
        )

    tests = (await session.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for t in tests:
        active = await _resolve_active_variant_label(session, t.id)
        winner = await _winner_label_for(session, t.id)
        out.append(_serialize_active(t, active, winner))
    return out


@router.get("/winners/since", response_model=list[WinnerEventOut])
async def winners_since(
    cursor: Annotated[int, Query(description="unix epoch ms")] = 0,
    user: CurrentUser = Depends(get_extension_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Новые winner-события с момента cursor (unix-ms).

    Источник: AbTestResult.computed_at + AbTest.completed_at >= cursor.
    SW зовёт раз в N минут (`pollIntervalMinutes` в options) и показывает
    chrome.notifications на каждое новое событие.
    """
    if cursor < 0:
        cursor = 0
    cutoff = datetime.fromtimestamp(cursor / 1000, tz=timezone.utc)

    stmt = (
        select(AbTest, AbTestVariant.label, AbTestResult.computed_at)
        .join(AbTestResult, AbTestResult.abtest_id == AbTest.id)
        .join(AbTestVariant, AbTestVariant.id == AbTestResult.winner_variant_id)
        .where(
            AbTestResult.winner_variant_id.is_not(None),
            AbTestResult.computed_at > cutoff,
        )
        .order_by(AbTestResult.computed_at.asc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    return [
        WinnerEventOut(
            testId=str(t.id),
            testName=t.name,
            nmId=t.nm_id,
            winnerVariantLabel=label,
            detectedAt=computed_at.isoformat(),
        ).model_dump()
        for (t, label, computed_at) in rows
    ]


@router.post("/positions", status_code=204)
async def record_positions(
    payload: PositionsPayload,
    user: CurrentUser = Depends(get_extension_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Принимает позицию карточки из выдачи WB.

    TODO: пока no-op (только лог) — для production нужна отдельная таблица
    `abtest_position_snapshot(tenant_id, nm_id, query, position, page,
    collected_at)` и UI-страница «позиции по тестам». Это объяснит дисперсию
    показов между вариантами теста: если фото A было на 1-й странице, а B
    на 4-й — разница в трафике не от фото, а от позиции в SEO.
    """
    log.info(
        "[extension] positions: tenant=%s nm=%s q=%r pos=%s page=%s at=%s",
        user.tenant_id,
        payload.nmId,
        payload.query,
        payload.position,
        payload.page,
        payload.collectedAt,
    )
    return None


@router.post("/wb-token/save")
async def save_wb_token(
    payload: WbTokenSavePayload,
    user: CurrentUser = Depends(get_extension_user),
) -> dict[str, Any]:
    """Auto-token save endpoint — DEPRECATED.

    Расширение исторически отправляло JWT, полученный через cabinet
    `tokensjrpc`. Проверка показала: tokensjrpc возвращает
    cabinet-session token, не Personal API token (см. UI options.tsx
    «🔑 Auto-token (НЕДОСТУПНО)»).

    Поэтому endpoint оставлен как stub, возвращает 400 и сразу настраивает
    клиента на ручной ввод токена в /settings основного UI.
    """
    raise HTTPException(
        400,
        "auto-token deprecated: tokensjrpc returns cabinet-session, "
        "not Personal API token. Add WB token manually in /settings.",
    )


@router.get("/wb-token/status", response_model=WbTokenStatusOut)
async def wb_token_status(
    user: CurrentUser = Depends(get_extension_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Текущий статус WB-токена tenant'а.

    Источник — `tenants.wb_token`. expiresAt декодируем из JWT (если это JWT).
    """
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.wb_token:
        return WbTokenStatusOut(
            hasToken=False,
            source=None,
            expiresAt=None,
            needsRefresh=True,
        ).model_dump()

    # WB-токены хранятся Fernet-зашифрованными (префикс `enc:`). Без
    # расшифровки JWT-декод даст мусор и `expiresAt`/`needsRefresh` будут
    # ошибочно null/false.
    from app.services.secrets_crypto import decrypt as _decrypt
    plain_token = _decrypt(tenant.wb_token) or ""

    expires_at_iso: str | None = None
    needs_refresh = True  # default: если не смогли распарсить exp — лучше показать refresh
    try:
        # Quick-and-dirty JWT payload decode (3 segments, no signature check)
        import base64
        import json

        parts = plain_token.split(".")
        if len(parts) >= 2:
            seg = parts[1].replace("-", "+").replace("_", "/")
            seg += "=" * ((-len(seg)) % 4)
            payload = json.loads(base64.b64decode(seg))
            exp = payload.get("exp")
            if isinstance(exp, (int, float)):
                expires_at_iso = (
                    datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
                )
                # Refresh, если до истечения < 7 дней
                seconds_left = int(exp) - int(
                    datetime.now(timezone.utc).timestamp()
                )
                needs_refresh = seconds_left < 7 * 24 * 3600
    except (ValueError, KeyError, TypeError):
        # Если токен не JWT-формата (legacy short token) — needs_refresh
        # остаётся True (UI покажет «обновите токен»).
        pass

    return WbTokenStatusOut(
        hasToken=True,
        source="manual",  # auto-source deprecated
        expiresAt=expires_at_iso,
        needsRefresh=needs_refresh,
    ).model_dump()
