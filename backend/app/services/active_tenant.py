"""Active tenant resolver — middleware + dependency для multi-cabinet workspace.

**Контекст** (TASK-LEAD-048 / TASK-LEAD-039 Фаза B): один user может иметь
доступ к нескольким `tenants` (см. таблица `user_tenant_access`, миграция
0056). Какой из них «active» в текущем request'е — определяется по приоритету:

1. cookie `rnp_active_tenant=<int>` — основной источник правды (HttpOnly,
   Lax, max_age=30d). Устанавливается через `POST /api/auth/switch-tenant`.
2. header `X-Tenant-ID: <int>` — для extension / API-токенов (cookie
   недоступна в MV3 SW в кросс-доменных запросах).
3. Fallback — первый доступный из `user_tenant_access` для user'а
   (стабильно: ordered by `last_active_at DESC NULLS LAST, tenant_id ASC`,
   берём первый).

Если cookie/header указывает на tenant, к которому user **не имеет
access** — middleware возвращает 403 (а НЕ молча подменяет на fallback,
иначе вектор атаки: подделанная cookie получит доступ к чужому tenant'у —
ну ладно подделать cookie невозможно из-за HttpOnly+Secure, но всё равно
лучше fail-loud).

**Middleware регистрируется в `main.py`** ПОСЛЕ `auth_gate`. К моменту
вызова `active_tenant_middleware` cookie/Bearer уже проверены.

**Запись:** `request.state.active_tenant_id: int | None` —
для downstream dependency `get_db_tenant_scoped` (она читает это поле
прежде чем пасть на `user.tenant_id`).
`request.state.effective_role: str | None` — per-tenant роль из
`user_tenant_access.role` (может отличаться от `user.role` в БД, если в
другом кабинете user — другая роль).

**Аутентификация ВСЁ ЕЩЁ через `services/auth.get_current_user`**.
Middleware не подменяет `user.tenant_id` напрямую — только пишет
override в `request.state`, чтобы downstream-код мог использовать.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.config import settings as cfg
from app.db.models import User, UserTenantAccess
from app.db.session import SessionLocal
from app.services.auth import decode_session_token


log = logging.getLogger(__name__)

ACTIVE_TENANT_COOKIE = "rnp_active_tenant"
TENANT_HEADER = "X-Tenant-ID"


async def _resolve_user_id_from_request(request: Request) -> int | None:
    """Достать user_id из cookie/Bearer токена.

    Дублирует часть логики `get_current_user` чтобы middleware не зависело
    от FastAPI DI. Возвращает None если токен не валиден / отсутствует
    (тогда middleware просто пропускает запрос — auth_gate уже его
    отфильтровал на public-paths).
    """
    token = request.cookies.get(cfg.auth_cookie_name)
    payload = decode_session_token(token) if token else None
    if not payload:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            payload = decode_session_token(bearer)
    if not payload:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


async def _load_access_for_user(user_id: int) -> dict[int, UserTenantAccess]:
    """Прочитать `user_tenant_access` для user'а. Возвращает dict
    {tenant_id: UserTenantAccess} для O(1) lookup.

    Открывает свежую AsyncSession через SessionLocal — НЕ depend от
    request-scoped DB (мы middleware, не handler). Engine один на процесс,
    привязан к main event-loop'у — это безопасно (см. `db/session.py`).
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(UserTenantAccess).where(UserTenantAccess.user_id == user_id)
            )
        ).scalars().all()
    return {a.tenant_id: a for a in rows}


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def active_tenant_middleware(request: Request, call_next: Any) -> Any:
    """Резолвит active_tenant_id для каждого request'а.

    Источники по приоритету: cookie `rnp_active_tenant` → header
    `X-Tenant-ID` → fallback (первый available из user_tenant_access,
    sorted by last_active_at DESC NULLS LAST, tenant_id ASC).

    Записывает:
      - `request.state.active_tenant_id: int | None`
      - `request.state.effective_role: str | None` (per-tenant роль)

    Если cookie/header указывает на forbidden tenant — JSON 403.
    Если у user'а вообще нет access (broken state) — JSON 403.
    """
    path = request.url.path

    # Не-API пути и публичные эндпоинты — middleware не нужен.
    if not path.startswith("/api/"):
        return await call_next(request)
    # PUBLIC_PATHS не имеют user'а — нечего резолвить.
    from app.services.auth import PUBLIC_PATHS  # local import — не циклить

    if path in PUBLIC_PATHS:
        return await call_next(request)
    # WB photo proxy — без auth, без tenant.
    if path.startswith("/api/products/") and path.endswith("/photo"):
        return await call_next(request)

    user_id = await _resolve_user_id_from_request(request)
    if user_id is None:
        # Не залогинен — auth_gate сам пропустил / вернёт 401. Middleware
        # ничего не делает, чтобы не подменять обработку ошибки.
        return await call_next(request)

    try:
        access = await _load_access_for_user(user_id)
    except Exception as e:  # noqa: BLE001 — middleware не должен ронять процесс
        log.exception("active_tenant_middleware: failed to load access: %s", e)
        return await call_next(request)

    if not access:
        # Broken state: user существует, но без access. Может случиться
        # если миграция 0056 не прошла backfill (например ручной DELETE).
        # Возвращаем 403 — пусть admin исправит.
        return JSONResponse(
            {"detail": "Нет доступа ни к одному tenant'у — обратитесь к директору"},
            status_code=403,
        )

    # Источник 1: cookie
    requested_tid = _parse_int(request.cookies.get(ACTIVE_TENANT_COOKIE))
    # Источник 2: header (фолбэк / extension)
    if requested_tid is None:
        requested_tid = _parse_int(request.headers.get(TENANT_HEADER))

    if requested_tid is not None:
        if requested_tid not in access:
            # Cookie/header указывают на forbidden tenant — fail-loud.
            return JSONResponse(
                {
                    "detail": (
                        f"Нет доступа к кабинету id={requested_tid}. "
                        "Возможно, доступ был отозван — выберите другой кабинет."
                    ),
                    "code": "tenant_forbidden",
                },
                status_code=403,
            )
        active_tid = requested_tid
    else:
        # Fallback: сортируем по last_active_at DESC NULLS LAST, потом
        # tenant_id ASC. Берём первый.
        sorted_access = sorted(
            access.values(),
            key=lambda a: (
                # NULLS LAST: None трактуем как самый «старый».
                a.last_active_at is None,
                # DESC: invert через negative timestamp (или используем
                # -timestamp.timestamp()). Но проще — ставим None после
                # реальных дат и сортируем реальные DESC.
                -(a.last_active_at.timestamp() if a.last_active_at else 0),
                a.tenant_id,
            ),
        )
        active_tid = sorted_access[0].tenant_id

    request.state.active_tenant_id = active_tid
    request.state.effective_role = access[active_tid].role

    return await call_next(request)


def get_active_tenant_id(request: Request) -> int | None:
    """Хелпер для handler'ов — достать active_tenant_id из request.state.

    Возвращает None если middleware не отработал (например public-path
    или middleware зафейлился). Caller должен fallback'ом подставить
    `user.tenant_id` (см. `get_db_tenant_scoped`).
    """
    return getattr(request.state, "active_tenant_id", None)


def get_effective_role(request: Request) -> str | None:
    """Хелпер для handler'ов — достать per-tenant role из request.state."""
    return getattr(request.state, "effective_role", None)
