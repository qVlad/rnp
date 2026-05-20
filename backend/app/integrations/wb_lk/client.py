"""HTTP-клиент для seller-weekly-report.wildberries.ru (shifts API).

См. WB_API_REFERENCE §13 + REDISTRIBUTION_PLAN §6.1.1.

Host: `seller-weekly-report.wildberries.ru`, базовый путь
`/ns/shifts/analytics-back/api/v1/`. Транспорт HTTP/2, JSON.

Auth: два JWT через `LkTokens` (см. `auth.py`). Wb-Seller-Lk обновляется
автоматически когда до истечения < 60 сек.

Endpoints: GET /nms, /stocks, /quota и POST /order (создание заявки на
перемещение). Спецификации расшифрованы из HAR (см. REDISTRIBUTION_PLAN
§6.1.1 + tmp/redistribution_har/2seller.wildberries.ru.har).

В production execute_window ходит в WB не через этот клиент напрямую
(IP-binding + JWT in-memory у WB-фронта блокируют server-side вызовы),
а через Chrome-extension proxy (`services/redistribution/extension_jobs.py`).
Этот клиент используется для оффлайн-разбора HAR и интеграционных тестов.
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
        # Circuit breaker: если refresh-endpoint вернул 401 — все следующие
        # запросы в рамках этого client'а сразу отдают ту же ошибку без
        # повторных попыток (иначе в логи летит спам "refreshing..."
        # десятки раз подряд при batch-обработке SKU'шек в recommender).
        # См. LEAD-016 follow-up: refresh endpoint TBD.
        self._refresh_broken: LkClientError | None = None

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
        """Refresh Wb-Seller-Lk если до истечения < 60 сек.

        Circuit breaker: при первом fail все следующие вызовы сразу
        перевыбрасывают ту же ошибку без обращения к WB. Это нужно
        потому что recommender вызывает get_stocks для каждой SKU и
        без breaker мы получили бы 50 одинаковых refresh-запросов в логи.
        """
        if self._refresh_broken is not None:
            raise self._refresh_broken
        if not is_expired(self.tokens.wb_seller_lk):
            return
        log.info("wb_lk: refreshing Wb-Seller-Lk (5min TTL expiring)")
        try:
            new_token = await refresh_wb_seller_lk(
                authorize_v3=self.tokens.authorize_v3,
                user_agent=self.tokens.user_agent,
            )
        except LkAuthError as e:
            err = LkClientError(f"token refresh failed: {e}", status=401)
            self._refresh_broken = err
            raise err from e
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

    # ─── POST /order — создание заявки на перемещение ────────────────
    # Endpoint и формат расшифрованы из HAR 2026-05-19 (см.
    # tmp/redistribution_har/2seller.wildberries.ru.har).

    async def create_order(
        self,
        *,
        src_office_id: int,
        dst_office_id: int,
        nm_id: int,
        items: list[tuple[int, int]],
    ) -> dict[str, Any]:
        """POST /ns/shifts/analytics-back/api/v1/order — создать заявку.

        `items` — список (chrt_id, qty). Можно отправить несколько chrtID
        одной заявкой для пары (src, dst, nmID) — это требование WB
        (одна заявка = один nmID, но разные характеристики/размеры
        внутри).

        Возвращает `{"success": true}` при удаче. LkClientError при
        логической ошибке WB (например, лимит исчерпан) — поскольку WB
        запаковывает их в response.error=true, наш _get переводит в
        исключение автоматически.

        Минимум qty: 1 единица (проверено на реальной заявке).
        """
        assert self._client is not None, "use as async context manager"
        await self._ensure_fresh_lk_token()
        body = {
            "order": {
                "src": int(src_office_id),
                "dst": int(dst_office_id),
                "nmID": int(nm_id),
                "count": [
                    {"chrtID": int(chrt_id), "count": int(qty)}
                    for chrt_id, qty in items
                ],
            }
        }
        try:
            resp = await self._client.post("/order", json=body)
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
        if isinstance(data, dict) and data.get("error"):
            raise LkClientError(
                f"WB-logical error: {data.get('errorText')!r}",
                status=resp.status_code,
                body=resp.text[:500],
            )
        return (data or {}).get("data") if isinstance(data, dict) else data
