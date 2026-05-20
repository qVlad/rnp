"""Authentication primitives — password hashing, JWT, FastAPI dependencies.

Design choices:
- **bcrypt** for password hashing (industry standard, slow-by-design = brute
  resistance). Salt is bundled into the hash string, no separate column.
- **JWT in HttpOnly cookie** for session — prevents XSS exfiltration that an
  Authorization-header SPA would be vulnerable to. SameSite=Lax for CSRF.
- **Short-lived tokens** (12h default) — no refresh-flow yet; user logs in
  once a day. Trade-off vs full session table — simpler to operate.
- **Roles**: `director` = full access; `manager` = read-most + edit-some
  (products, groups, plans). Sensitive endpoints (settings, OPEX, налоги,
  audit-log full read) are wrapped with `require_role("director")`.

Bootstrap (first-run): if no users exist, `POST /api/auth/bootstrap` creates
the first director account. After that, the bootstrap endpoint refuses.
Subsequent users created via `POST /api/users/` (director only).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as cfg
from app.db.models import User
from app.db.session import get_db

# ─── Roles ────────────────────────────────────────────────────────────────

ROLES: tuple[str, ...] = ("director", "head_of_sales", "manager")


@dataclass
class CurrentUser:
    """Resolved request-scoped user. Use in handlers via `Depends(get_current_user)`."""

    id: int
    username: str
    role: str
    full_name: str | None
    tenant_id: int

    @property
    def is_director(self) -> bool:
        return self.role == "director"

    @property
    def sees_all_brands(self) -> bool:
        """director and head_of_sales see all brands; manager only their own."""
        return self.role in ("director", "head_of_sales")


# ─── Password hashing ─────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Bcrypt-hash a plaintext password. Returns the hash string with embedded salt."""
    if not plain:
        raise ValueError("password must not be empty")
    if len(plain) > 72:
        # bcrypt silently truncates beyond 72 bytes — reject explicitly so
        # the user knows their long password isn't fully used.
        raise ValueError("password must not exceed 72 bytes")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ─── JWT ──────────────────────────────────────────────────────────────────


def create_session_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "u": user.username,
        "r": user.role,
        # tenant_id — обязательное поле в multi-tenant; все API
        # фильтруют запросы по этому значению.
        "t": int(user.tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=cfg.jwt_expires_hours)).timestamp()),
    }
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm)


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, cfg.jwt_secret_key, algorithms=[cfg.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.PyJWTError:
        return None


# ─── Cookie helpers ───────────────────────────────────────────────────────


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=cfg.auth_cookie_name,
        value=token,
        max_age=cfg.jwt_expires_hours * 3600,
        httponly=True,
        secure=cfg.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=cfg.auth_cookie_name,
        path="/",
        secure=cfg.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


# ─── FastAPI dependencies ─────────────────────────────────────────────────

# Public endpoints (don't require auth). Anything else is gated by
# get_current_user — declare in a tuple so middleware/router can opt-out
# without touching this file.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/api/health",
    "/api/whoami",
    "/api/version",
    "/api/auth/login",
    "/api/auth/bootstrap",
    "/api/auth/needs-bootstrap",
    "/api/auth/signup",
})


async def _users_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(User.id)))).scalar() or 0)


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Resolve the user from the session cookie OR `Authorization: Bearer <jwt>`.

    Primary path — HttpOnly cookie `rnp_session` (set by /api/auth/login).
    Fallback — Bearer header (same JWT, удобно для CLI / Chrome-расширения /
    внешних интеграций). Соответствует логике `auth_gate` middleware в main.py.

    Enforces "active" — disabled users (admin can flip is_active off) are
    immediately locked out without invalidating tokens (since they're stateless).
    """
    token = request.cookies.get(cfg.auth_cookie_name)
    payload = decode_session_token(token) if token else None
    if not payload:
        # Fallback: Authorization: Bearer <jwt>
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            payload = decode_session_token(bearer)
    if not payload:
        raise HTTPException(401, "not authenticated")
    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(401, "session payload malformed") from e
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


def require_role(*allowed_roles: str):
    """Returns a dependency that enforces the role list.

    Usage::

        @router.put("/settings", dependencies=[Depends(require_role("director"))])
        async def put_settings(...): ...
    """

    async def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                403,
                f"role {user.role!r} cannot perform this action; "
                f"required: {sorted(allowed_roles)}",
            )
        return user

    return _checker


# Convenience dependency aliases
require_director = require_role("director")
require_director_or_head = require_role("director", "head_of_sales")


async def get_db_tenant_scoped(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """FastAPI dependency: вернуть session с уже выставленным tenant_id.

    Все ORM SELECT через эту сессию автоматически фильтруются по
    `tenant_id` текущего юзера (event listener в `tenant_context.py`).
    Новые объекты тоже получают tenant_id автоматически (before_flush).

    Используй вместо `Depends(get_db)` во **всех** protected endpoints,
    кроме `/api/auth/*` — там tenant ещё не известен.
    """
    from app.services.tenant_context import set_tenant  # noqa: WPS433

    set_tenant(session, user.tenant_id)
    return session


async def current_tenant_id(user: CurrentUser = Depends(get_current_user)) -> int:
    """Хелпер: возвращает tenant_id текущего юзера из JWT.

    Удобно подключать как `Depends(current_tenant_id)` в API endpoint'ах
    и использовать в фильтрах SQL: `.where(Model.tenant_id == tenant_id)`.
    """
    return user.tenant_id


async def current_brands_filter(
    user: "CurrentUser" = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> set[str] | None:
    """Return the brand whitelist for the current user.

    `None` ⇒ unrestricted (director, head_of_sales).
    `set[str]` ⇒ manager — only data for these brands. Empty set is valid
    and means "show nothing" — manager has no brand assignments yet.
    """
    if user.sees_all_brands:
        return None
    # Local import — avoid models <-> services circular import at module load.
    from app.db.models import BrandAssignment  # noqa: WPS433

    rows = (
        await session.execute(
            select(BrandAssignment.brand).where(
                BrandAssignment.user_id == user.id,
                BrandAssignment.tenant_id == user.tenant_id,
            )
        )
    ).scalars().all()
    return {b for b in rows if b}
