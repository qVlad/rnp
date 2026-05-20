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
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AbTest,
    AbTestDailyStat,
    AbTestPositionSnapshot,
    AbTestResult,
    AbTestRotation,
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


async def _resolve_active_variant(
    session: AsyncSession, abtest_id: int
) -> tuple[str, int | None, datetime | None]:
    """Возвращает (label, variant_id, last_rotation_at) для активного варианта.

    Активный вариант = вариант последней успешной ротации (AbTestRotation.success=True).
    Если ротаций ещё не было (только что запущенный тест) — возвращаем первый
    not-eliminated вариант по алфавиту и last_rotation_at=None.

    Используется и для отображения active label, и для расчёта прогресса
    (от какого момента считать views/spend/time).
    """
    # 1) Пробуем найти последнюю успешную ротацию.
    rot_row = (
        await session.execute(
            select(AbTestRotation.applied_at, AbTestVariant.label, AbTestVariant.id)
            .join(AbTestVariant, AbTestVariant.id == AbTestRotation.variant_id)
            .where(
                AbTestRotation.abtest_id == abtest_id,
                AbTestRotation.success.is_(True),
            )
            .order_by(desc(AbTestRotation.applied_at))
            .limit(1)
        )
    ).first()
    if rot_row is not None:
        applied_at, label, variant_id = rot_row
        return label, variant_id, applied_at

    # 2) Ротаций не было — берём первый not-eliminated вариант.
    row = (
        await session.execute(
            select(AbTestVariant.label, AbTestVariant.id)
            .where(
                AbTestVariant.abtest_id == abtest_id,
                AbTestVariant.eliminated_at.is_(None),
            )
            .order_by(AbTestVariant.label)
            .limit(1)
        )
    ).first()
    if row is None:
        return "A", None, None
    label, variant_id = row
    return label, variant_id, None


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


async def _compute_progress_and_next_rotation(
    session: AsyncSession,
    test: AbTest,
    active_variant_id: int | None,
    last_rotation_at: datetime | None,
) -> tuple[int, str | None]:
    """Считаем прогресс выборки (%) и ISO timestamp следующей ротации.

    Логика зависит от `trigger_mode`:

    **TIME** — самое предсказуемое. anchor = last_rotation_at OR started_at;
    next_rotation_at = anchor + trigger_value*60 sec;
    progress = (now - anchor) / (trigger_value*60) × 100.

    **VIEWS** — прогресс по показам **текущего активного варианта** с момента
    последней ротации (или старта теста). AbTestDailyStat хранит дневные
    агрегаты — складываем impressions всех записей с stat_date >= anchor_date.
    Гранулярность 1 день — это даёт ±1 день погрешности, для badge'а ОК.
    next_rotation_at = null (нельзя предсказать velocity показов).

    **BUDGET** — сумма ad_spend всех вариантов теста с момента anchor.
    next_rotation_at = null (нельзя предсказать velocity трат).

    Все ошибки → (0, None) — badge просто покажет 0% без таймера.
    """
    if test.trigger_value <= 0:
        return 0, None

    # Anchor — от какого момента считаем прогресс.
    anchor = last_rotation_at or test.started_at
    if anchor is None:
        return 0, None

    now = datetime.now(timezone.utc)

    mode = test.trigger_mode
    if mode == "TIME":
        period_sec = test.trigger_value * 60
        elapsed_sec = (now - anchor).total_seconds()
        pct = max(0, min(100, int(elapsed_sec / period_sec * 100)))
        next_at = anchor + timedelta(seconds=period_sec)
        return pct, next_at.isoformat()

    if mode == "VIEWS":
        if active_variant_id is None:
            return 0, None
        # Sum impressions активного варианта с anchor_date по сегодня.
        # Используем `>=` по stat_date чтобы захватить день anchor целиком.
        result = await session.execute(
            select(func.coalesce(func.sum(AbTestDailyStat.impressions), 0))
            .where(
                AbTestDailyStat.variant_id == active_variant_id,
                AbTestDailyStat.stat_date >= anchor.date(),
            )
        )
        impressions = int(result.scalar() or 0)
        pct = max(0, min(100, int(impressions / test.trigger_value * 100)))
        return pct, None

    if mode == "BUDGET":
        # Сумма ad_spend всех вариантов теста с anchor_date.
        result = await session.execute(
            select(func.coalesce(func.sum(AbTestDailyStat.ad_spend), 0))
            .join(AbTestVariant, AbTestVariant.id == AbTestDailyStat.variant_id)
            .where(
                AbTestVariant.abtest_id == test.id,
                AbTestDailyStat.stat_date >= anchor.date(),
            )
        )
        spent = float(result.scalar() or 0)
        pct = max(0, min(100, int(spent / test.trigger_value * 100)))
        return pct, None

    return 0, None


def _serialize_active(
    test: AbTest,
    active_label: str,
    winner_label: str | None,
    progress_pct: int,
    next_rotation_at: str | None,
) -> dict[str, Any]:
    return ActiveTestOut(
        id=str(test.id),
        name=test.name,
        status=test.status,
        nmId=test.nm_id,
        activeVariantLabel=active_label,
        nextRotationAt=next_rotation_at,
        scenario=_scenario_for(test),
        winnerVariantLabel=winner_label,
        sampleProgressPct=progress_pct,
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
        active_label, active_variant_id, last_rotation_at = (
            await _resolve_active_variant(session, t.id)
        )
        winner = await _winner_label_for(session, t.id)
        pct, next_at = await _compute_progress_and_next_rotation(
            session, t, active_variant_id, last_rotation_at
        )
        out.append(_serialize_active(t, active_label, winner, pct, next_at))
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
    """Принимает позицию карточки из выдачи WB и сохраняет в БД.

    Сохраняем БЕЗ дедупа — частота нужна для оценки стабильности позиции.
    Дальнейшая аналитика по этим данным — через `GET /api/abtest/{id}/positions`
    на стороне UI (раздел «Позиции в выдаче» на странице A/B-теста).

    Защиты:
      • Pydantic schema валидирует типы (nmId int, position int, page int)
      • Sanity-check значений ниже — если что-то выглядит абсурдно, отвечаем
        204 (не ломаем расширение), но в таблицу не пишем. Логируем для
        дебага.
      • Truncate query до 500 символов (схема), URL-длина WB поиска бывает
        большой.
    """
    if payload.position < 1 or payload.position > 100_000:
        log.warning(
            "[extension] positions: skip suspicious position=%s nm=%s tenant=%s",
            payload.position, payload.nmId, user.tenant_id,
        )
        return None
    if payload.page < 1 or payload.page > 1000:
        log.warning(
            "[extension] positions: skip suspicious page=%s nm=%s tenant=%s",
            payload.page, payload.nmId, user.tenant_id,
        )
        return None

    # collectedAt приходит от клиента — парсим как ISO. Если плохое значение,
    # используем now() в БД (created_at), а в collected_at тоже now().
    from datetime import datetime as _dt

    try:
        # JS пишет '2026-05-19T19:35:00.123Z' — Python принимает Z только с 3.11+.
        # Приведём 'Z' → '+00:00' для совместимости.
        collected = _dt.fromisoformat(payload.collectedAt.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        collected = _dt.now(timezone.utc)

    snap = AbTestPositionSnapshot(
        tenant_id=user.tenant_id,
        nm_id=payload.nmId,
        query=payload.query[:500],
        position=payload.position,
        page=payload.page,
        collected_at=collected,
    )
    session.add(snap)
    await session.commit()

    log.info(
        "[extension] positions saved: tenant=%s nm=%s q=%r pos=%s page=%s",
        user.tenant_id, payload.nmId, payload.query[:80],
        payload.position, payload.page,
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
