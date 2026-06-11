"""TrueStats API client (TASK-DEV-077) — источник OPEX-методологии.

TS учитывает ВСЕ операционные расходы (ФОТ/аренда/подписки) и распределяет их
по нескольким marketplace-аккаунтам одного владельца (`distribution`: equal /
proportional). Наш Onyx = один из аккаунтов; его доля OPEX = сумма аллокаций.

Используется `services/opex_ts_sync.py` для синка Onyx-доли OPEX в наш `/opex`.

Аутентификация: заголовок `x-auth-token` = TS authToken (120-hex из localStorage
залогиненной TS-сессии). Хранится в AppSetting `ts_auth_token` (per-tenant);
протухает → синк вернёт 401, нужно обновить токен. Хост `api2.truestats.ru`
(api.truestats.ru — IP-блок датацентров, использовать api2). Прод достукивается.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

TS_BASE = "https://api2.truestats.ru"
_TIMEOUT = 25.0


class TrueStatsError(Exception):
    """TS API вернул не-2xx (включая 401 — протухший токен)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body[:300]
        super().__init__(f"TS API {status}: {self.body}")


async def _post(token: str, path: str, body: dict[str, Any]) -> Any:
    headers = {"Content-Type": "application/json", "x-auth-token": token}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{TS_BASE}{path}", json=body, headers=headers)
    if resp.status_code != 200:
        raise TrueStatsError(resp.status_code, resp.text or "")
    return resp.json()


async def operation_list(
    token: str, *, date_from: date, date_to: date, account_id: int
) -> list[dict[str, Any]]:
    """Операции (расходы/доходы) за период по аккаунту. Возвращает `items[]`
    с полями amount/operationType/activityType/category/distribution/isConfirmed/
    isPlanned/retroactiveDateFrom (см. reverse-engineering в TASK-DEV-077)."""
    body = {
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
        "filters": {"accounts": [int(account_id)]},
    }
    j = await _post(token, "/v1/operation/list", body)
    return list(j.get("items") or [])


async def account_realisation(
    token: str, *, date_from: date, date_to: date, account_id: int
) -> float:
    """Реализация аккаунта за период (для proportional-распределения OPEX)."""
    body = {
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
        "filters": {"accounts": [int(account_id)]},
    }
    j = await _post(token, "/reporting/main/stats", body)
    return float((j.get("stats") or {}).get("realisation") or 0.0)
