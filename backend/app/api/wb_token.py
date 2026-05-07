"""WB token wizard / validator.

Decodes the JWT (no signature verification — we only inspect the public payload),
runs a single lightweight probe request, and returns a verdict the user can act on
BEFORE committing the token to .env.

The decoded JWT payload reveals:
  - acc:  account level
  - t:    is this a Test token?  (Test tokens have very strict rate limits)
  - exp:  expiry as unix timestamp
  - s:    bitmask of permission scopes
  - iid / oid: installation / owner ids

We don't enumerate every bit of `s` precisely — WB hasn't published a stable
public mapping. Instead we report `s` as-is and rely on the probe request to
check practical access.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings as cfg
from app.integrations.wb import cooldown as wb_cooldown
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive

router = APIRouter(prefix="/api/wb/token", tags=["wb-token"])


class TokenPayload(BaseModel):
    token: str | None = None  # if None — validate the token from .env


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode JWT payload (the middle segment) without verifying signature."""
    parts = token.strip().split(".")
    if len(parts) < 2:
        return None
    seg = parts[1]
    # base64url → base64 + padding
    seg = seg.replace("-", "+").replace("_", "/")
    pad = (-len(seg)) % 4
    seg += "=" * pad
    try:
        raw = base64.b64decode(seg)
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None


async def _probe(token: str) -> dict[str, Any]:
    """Send one lightweight request to WB and report status.

    SAFETY: this routes through `WbApiClient`, so the request:
      * is BLOCKED if the shared Redis cooldown for `statistics` is active —
        the validator does not waste a real call into a known penalty window
        and (more importantly) does not race with `worker-stats` syncs;
      * goes through the per-process rate limiter;
      * properly parses 429 reset headers to set the global cooldown.

    Probe URL: `/api/v1/supplier/orders?dateFrom=<far-future>&flag=0` — WB
    returns an empty list with full headers but ~no payload, which is the
    cheapest probe that still touches the Statistics scope.
    """
    # Probe shortcut: if cooldown active, do NOT call WB. Reading Redis is
    # free; sending a request right now would extend the WB-side penalty.
    remaining = await wb_cooldown.get_remaining("statistics")
    if remaining > 0:
        return {
            "status": -1,
            "body_preview": (
                f"Skipped: статистика-API в cooldown ещё ~{remaining}с. "
                f"Подождите и повторите — иначе на свежем токене сразу 429."
            ),
            "headers": {"x-cooldown-remaining": str(remaining)},
        }

    try:
        async with WbApiClient(token=token, timeout=15) as wb:
            try:
                await wb.get(
                    "/api/v1/supplier/orders",
                    category="statistics",
                    params={"dateFrom": "2099-01-01", "flag": 0},
                )
                return {
                    "status": 200,
                    "body_preview": "OK (token validated; 1 stats call burned)",
                    "headers": {},
                }
            except WbCooldownActive as e:
                return {
                    "status": -1,
                    "body_preview": f"Skipped: {e}",
                    "headers": {"x-cooldown-remaining": str(e.remaining)},
                }
            except WbApiError as e:
                return {
                    "status": e.status,
                    "body_preview": (e.body or "")[:300],
                    "headers": e.headers or {},
                }
    except (httpx.ConnectError, httpx.ReadTimeout) as e:
        return {"status": 0, "body_preview": f"transport error: {e}", "headers": {}}


@router.post("/validate")
async def validate_token(payload: TokenPayload) -> dict[str, Any]:
    """Decode + probe a WB token. If `token` is omitted, uses settings.wb_token (.env)."""
    token = (payload.token or "").strip() or cfg.wb_token or ""
    if not token:
        return {
            "ok": False,
            "source": "none",
            "error": "no token provided and TG_BOT_TOKEN not set in .env",
        }

    source = "request" if payload.token else "env"
    decoded = _decode_jwt_payload(token)
    decode_view: dict[str, Any] | None = None
    expiry_iso: str | None = None
    expired = False
    is_test = False
    if decoded:
        exp = decoded.get("exp")
        if isinstance(exp, (int, float)):
            try:
                expiry_iso = datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
                expired = int(exp) < int(datetime.now(timezone.utc).timestamp())
            except (ValueError, OSError):
                pass
        is_test = bool(decoded.get("t"))
        decode_view = {
            "acc": decoded.get("acc"),
            "t": is_test,
            "expires_at": expiry_iso,
            "expired": expired,
            "iid": decoded.get("iid"),
            "oid": decoded.get("oid"),
            "uid": decoded.get("uid"),
            "scope_bits": decoded.get("s"),
        }

    # Run probe (quick HEAD-style check via GET stocks)
    probe = await _probe(token)
    probe_status = int(probe.get("status") or 0)
    probe_ok = probe_status == 200

    # Build a verdict + recommendations
    issues: list[str] = []
    if decoded is None:
        issues.append("Не удалось декодировать JWT — это вообще валидный токен WB?")
    if expired:
        issues.append(f"Токен истёк: {expiry_iso}")
    if is_test:
        issues.append(
            "Это тестовый токен (t=true) — у него очень узкие лимиты. "
            "Создайте обычный токен в ЛК WB → Профиль → Доступ к API."
        )
    if probe_status == 401 or probe_status == 403:
        issues.append("WB вернул 401/403 — токен не имеет категории Statistics.")
    if probe_status == 429:
        issues.append(
            "WB вернул 429 — токен сейчас в penalty-окне. Подождите столько секунд, "
            "сколько указано в x-ratelimit-reset, и попробуйте снова."
        )
    if probe_status == -1:
        issues.append(
            "Probe пропущен из-за активного cooldown — это защита от race "
            "с другими syncs. Проверьте cooldown=0 и повторите."
        )

    return {
        "ok": probe_ok and not expired and not issues,
        "source": source,
        "decoded": decode_view,
        "probe": probe,
        "issues": issues,
        "verdict": (
            "Токен валиден и проходит probe-запрос."
            if (probe_ok and not issues)
            else "Есть проблемы — см. issues выше."
        ),
    }
