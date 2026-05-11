"""API: per-tenant настройки. Сейчас только WB-токен (Wildberries Seller API).

GET  /api/tenant/wb-token          → статус (валиден / нет / когда проверен)
PUT  /api/tenant/wb-token          → сохранить новый токен (+ валидация)
POST /api/tenant/wb-token/validate → проверить токен без сохранения

Только director может менять WB-токен (это даёт доступ к финансам компании).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.db.session import get_db
from app.integrations.wb.client import WbApiClient, WbApiError
from app.services.auth import CurrentUser, get_current_user, require_director
from app.services.secrets_crypto import encrypt

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


class WbTokenPayload(BaseModel):
    token: str


def _decode_wb_token_sid(token: str) -> str | None:
    """Извлекает `sid` (seller ID) из WB JWT без проверки подписи."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return str(payload.get("sid") or "") or None
    except Exception:
        return None


async def _ping_wb(token: str) -> tuple[bool, str | None]:
    """Делает один запрос к WB common-api/ping чтобы убедиться что токен живой.

    Возвращает (ok, error_msg).
    """
    try:
        async with WbApiClient(token=token) as wb:
            # /ping есть на каждом хосте; common даёт самый низкий лимит.
            await wb.get("/ping", category="common")
        return True, None
    except WbApiError as e:
        return False, f"WB ответил {e.status}: {e.message}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


@router.get("/wb-token")
async def get_wb_token_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Статус WB-токена текущего tenant'а. Сам токен НЕ возвращаем —
    только метаданные (есть/нет, последняя валидация, seller_id)."""
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    return {
        "set": bool(tenant.wb_token),
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": (
            tenant.wb_token_validated_at.isoformat()
            if tenant.wb_token_validated_at else None
        ),
    }


@router.put("/wb-token", dependencies=[Depends(require_director)])
async def set_wb_token(
    payload: WbTokenPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сохранить токен. Валидирует /ping перед сохранением — если WB
    ответил 401/403, токен не сохраняется."""
    token = payload.token.strip()
    if not token or len(token) < 100:
        raise HTTPException(400, "token слишком короткий (ожидается JWT)")

    ok, err = await _ping_wb(token)
    if not ok:
        raise HTTPException(400, f"токен не прошёл валидацию: {err}")

    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    # Шифруем перед сохранением (Fernet) — если ключ настроен; иначе
    # plaintext + warning в логах.
    tenant.wb_token = encrypt(token)
    tenant.wb_token_validated_at = datetime.now(timezone.utc)
    tenant.wb_token_seller_id = _decode_wb_token_sid(token)
    await session.commit()
    return {
        "set": True,
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": tenant.wb_token_validated_at.isoformat(),
    }


@router.post("/wb-token/validate", dependencies=[Depends(require_director)])
async def validate_wb_token(payload: WbTokenPayload) -> dict[str, Any]:
    """Проверить токен без сохранения. Полезно перед PUT — UI делает
    проверку при потере фокуса на поле."""
    token = payload.token.strip()
    if not token:
        raise HTTPException(400, "token обязателен")
    ok, err = await _ping_wb(token)
    return {
        "valid": ok,
        "error": err,
        "seller_id": _decode_wb_token_sid(token) if ok else None,
    }


@router.delete("/wb-token", dependencies=[Depends(require_director)])
async def clear_wb_token(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Удалить токен (sync остановится после очистки)."""
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    tenant.wb_token = None
    tenant.wb_token_validated_at = None
    tenant.wb_token_seller_id = None
    await session.commit()
    return {"cleared": True}
