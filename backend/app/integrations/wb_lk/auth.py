"""WB LK session-capture auth: загрузка / refresh JWT-токенов.

См. WB_API_REFERENCE §13 + REDISTRIBUTION_PLAN §6.1.1.

Авторизация — **два JWT в headers** (cookies не нужны):
  - `AuthorizeV3` — RS256, долгоживущий (часы/дни). Получается через
    SMS-логин на seller.wildberries.ru.
  - `Wb-Seller-Lk` — EdDSA, TTL ровно 5 минут. Refresh через
    `POST /ns/suppliers-auth/.../auth/token` JSON-RPC.

**В этой итерации SMS-логин flow НЕ автоматизирован** — токены добавляются
руками через UI (страница `/redistribution` → «Подключить LK»). Юзер сам
получает их через DevTools после логина в seller.wildberries.ru. SMS+captcha
automation — отдельная задача (требует RuCaptcha / Telegram-interactive flow).
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)


SUPPLIERS_AUTH_TOKEN_URL = (
    "https://seller.wildberries.ru/ns/suppliers-auth/suppliers-portal-core/auth/token"
)

# Wb-Seller-Lk TTL ровно 5 мин. Refresh запускаем за 60 сек до истечения —
# тогда даже если refresh займёт несколько сек / упадёт, у нас есть запас.
REFRESH_LEEWAY_SECONDS = 60


@dataclass
class LkTokens:
    """Пара токенов для одного запроса к shifts API."""

    authorize_v3: str
    wb_seller_lk: str
    root_version: str = "v1.93.1"  # обновлять при детекте version mismatch
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    )


class LkAuthError(Exception):
    """Auth-related ошибка: токен невалиден / истёк / WB вернул 401."""


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Декодирует JWT payload без верификации подписи (нам нужно только exp/iat).

    JWT = header.payload.signature, все base64url. Подпись WB мы всё равно не
    можем проверить (приватный ключ только у них).
    """
    try:
        _hdr, payload_b64, _sig = token.split(".")
        # base64url with padding fixup
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise LkAuthError(f"malformed JWT: {e}") from e


def extract_exp(token: str) -> datetime:
    """exp из JWT payload как aware datetime (UTC)."""
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise LkAuthError("JWT has no numeric exp")
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def extract_seller_lk_context(token: str) -> dict[str, str]:
    """Из Wb-Seller-Lk JWT достаёт supplier_fid, supplier_oid, z_sid.

    Payload вида:
        {"data": {"Z-Sfid": "867165", "Z-Soid": "867165",
                  "Z-Sid": "549ff7a0-...", "Z-Slfid": "11"}, ...}
    """
    payload = _decode_jwt_payload(token)
    data = payload.get("data") or {}
    return {
        "supplier_fid": str(data.get("Z-Sfid", "")),
        "supplier_oid": str(data.get("Z-Soid", "")),
        "z_sid": str(data.get("Z-Sid", "")),
    }


def is_expired(token: str, leeway_seconds: int = REFRESH_LEEWAY_SECONDS) -> bool:
    """True если до истечения < leeway секунд (или уже истёк)."""
    try:
        exp = extract_exp(token)
    except LkAuthError:
        return True
    now = datetime.now(timezone.utc)
    return (exp - now).total_seconds() < leeway_seconds


async def refresh_wb_seller_lk(
    *,
    authorize_v3: str,
    user_agent: str,
    timeout_s: float = 5.0,
) -> str:
    """Получить свежий Wb-Seller-Lk JWT через JSON-RPC endpoint.

    Возвращает новый токен (string) или raises LkAuthError при 4xx/5xx.
    Сам токен либо в заголовке ответа `Wb-Seller-Lk`, либо в body JSON
    (в зависимости от server-side контракта; проверяем оба).
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "AuthorizeV3": authorize_v3,
        "Origin": "https://seller.wildberries.ru",
        "Referer": "https://seller.wildberries.ru/",
        "User-Agent": user_agent,
    }
    body = {"params": {}, "jsonrpc": "2.0", "id": "json-rpc_10"}

    async with httpx.AsyncClient(timeout=timeout_s, http2=True) as client:
        try:
            resp = await client.post(
                SUPPLIERS_AUTH_TOKEN_URL, headers=headers, json=body
            )
        except httpx.HTTPError as e:
            raise LkAuthError(f"network error: {e}") from e

    if resp.status_code == 401:
        raise LkAuthError("AuthorizeV3 expired or invalid — needs SMS relogin")
    if resp.status_code >= 400:
        raise LkAuthError(
            f"refresh failed status={resp.status_code} body={resp.text[:200]!r}"
        )

    # 1. Header: предпочтительный путь (как у фронта seller.wildberries.ru)
    header_token = resp.headers.get("Wb-Seller-Lk") or resp.headers.get(
        "wb-seller-lk"
    )
    if header_token:
        return header_token

    # 2. Body fallback: JSON-RPC result.token / result.wb_seller_lk
    try:
        data = resp.json()
    except Exception as e:
        raise LkAuthError(f"unparseable response: {e}") from e
    result = (data or {}).get("result") or {}
    for key in ("token", "wb_seller_lk", "wbSellerLk", "wbSellerLK"):
        token = result.get(key)
        if isinstance(token, str) and token.count(".") == 2:
            return token

    raise LkAuthError(f"no Wb-Seller-Lk in response: {data!r}")
