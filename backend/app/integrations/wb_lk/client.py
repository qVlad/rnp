"""HTTP-клиент для seller-weekly-report.wildberries.ru (shifts API).

См. WB_API_REFERENCE §13 + REDISTRIBUTION_PLAN §6.1.1.

Host: `seller-weekly-report.wildberries.ru`, базовый путь
`/ns/shifts/analytics-back/api/v1/`. Транспорт HTTP/2, JSON.

Auth: два JWT через `LkTokens` (см. `auth.py`). Wb-Seller-Lk обновляется
автоматически когда до истечения < 60 сек.

В этом клиенте — только GET endpoints из HAR (nms, stocks, quota).
POST shifts.create требует отдельного HAR (см. REDISTRIBUTION_PLAN §6.1
TODO) и будет добавлен после.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.wb_lk.auth import LkAuthError, LkTokens, is_expired, refresh_wb_seller_lk

log = logging.getLogger(__name__)


BASE_URL = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1"


class LkClientError(Exception):
    """LK API вернул ошибку (4xx/5xx) или сетевой fail."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _build_headers(tokens: LkTokens) -> dict[str, str]:
    return {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "AuthorizeV3": tokens.authorize_v3,
        "Wb-Seller-Lk": tokens.wb_seller_lk,
        "Content-Type": "application/json",
        "Origin": "https://seller.wildberries.ru",
        "Referer": "https://seller.wildberries.ru/",
        "Root-Version": tokens.root_version,
        "User-Agent": tokens.user_agent,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }


class WbLkClient:
    """Контекст-менеджер с persistent HTTP/2 connection.

    Usage:
        async with WbLkClient(tokens) as lk:
            stocks = await lk.get_stocks(nm_id=231830095)
            quota = await lk.get_quota(office_id=130744, kind="src")
    """

    def __init__(
        self,
        tokens: LkTokens,
        *,
        timeout_s: float = 8.0,
        on_token_refreshed=None,  # callback(new_lk_token: str) → persist в БД
    ):
        self.tokens = tokens
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None
        self._on_token_refreshed = on_token_refreshed

    async def __aenter__(self) -> "WbLkClient":
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=self._timeout,
            http2=True,
            headers=_build_headers(self.tokens),
        )
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def _ensure_fresh_lk_token(self) -> None:
        """Refresh Wb-Seller-Lk если до истечения < 60 сек."""
        if not is_expired(self.tokens.wb_seller_lk):
            return
        log.info("wb_lk: refreshing Wb-Seller-Lk (5min TTL expiring)")
        try:
            new_token = await refresh_wb_seller_lk(
                authorize_v3=self.tokens.authorize_v3,
                user_agent=self.tokens.user_agent,
            )
        except LkAuthError as e:
            raise LkClientError(f"token refresh failed: {e}", status=401) from e
        self.tokens.wb_seller_lk = new_token
        if self._client is not None:
            self._client.headers["Wb-Seller-Lk"] = new_token
        if self._on_token_refreshed:
            try:
                await self._on_token_refreshed(new_token)
            except Exception:
                log.exception("on_token_refreshed callback failed")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        assert self._client is not None, "use as async context manager"
        await self._ensure_fresh_lk_token()
        try:
            resp = await self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise LkClientError(f"network error: {e}") from e
        if resp.status_code == 401:
            raise LkClientError(
                "401 from shifts API — token invalid",
                status=401,
                body=resp.text[:500],
            )
        if resp.status_code >= 400:
            raise LkClientError(
                f"shifts API {resp.status_code}",
                status=resp.status_code,
                body=resp.text[:500],
            )
        data = resp.json()
        # WB-style envelope: {data: ..., error: bool, errorText: str, additionalErrors: null}
        if isinstance(data, dict) and data.get("error"):
            raise LkClientError(
                f"shifts API logical error: {data.get('errorText')!r}",
                status=resp.status_code,
                body=resp.text[:500],
            )
        return (data or {}).get("data") if isinstance(data, dict) else data

    # ─── Endpoints из HAR §6.1.1 ────────────────────────────────────

    async def search_nms(self, pattern: str) -> list[dict[str, Any]]:
        """Поиск артикулов по строке. Возвращает list of {nmID, subjectName}."""
        result = await self._get("/nms", params={"pattern": pattern})
        return (result or {}).get("nms") or []

    async def get_stocks(self, nm_id: int) -> list[dict[str, Any]]:
        """Остатки по складам с chrt_id. Возвращает массив `src` —
        каждый элемент: {officeName, officeID, inStock: [{chrtID, count, techSize}]}.
        Это **ключевой endpoint** — выдаёт chrt_id для создания заявки.
        """
        result = await self._get("/stocks", params={"nmID": nm_id})
        return (result or {}).get("src") or []

    async def get_quota(self, office_id: int, kind: str = "src") -> int:
        """Квота на склад (`src` = источник, `dst` = приёмник).

        Возвращает целое число:
          - 0 = окно закрыто, перемещение сейчас невозможно
          - >0 = окно открыто, можно создать заявку с qty до `quota`

        **Главная точка polling** для окон 09:00 / 18:00 МСК.
        """
        if kind not in ("src", "dst"):
            raise ValueError(f"kind must be 'src' or 'dst', got {kind!r}")
        result = await self._get("/quota", params={"officeID": office_id, "type": kind})
        return int((result or {}).get("quota", 0))

    # ─── POST create_shift — TODO ────────────────────────────────────
    # Path и body неизвестны (нет HAR с актом создания заявки). См.
    # REDISTRIBUTION_PLAN.md §6.1 «Endpoints которых НЕТ в HAR».
    # Snapshot нужен на момент клика «Создать перемещение» в LK WB.
    #
    # Ожидаемая сигнатура:
    #   async def create_shift(
    #       self, *, chrt_id: int, from_office_id: int,
    #       to_office_id: int, qty: int,
    #   ) -> dict
    #
    # Пока возвращаем NotImplementedError — это сигнал что нужен HAR.
