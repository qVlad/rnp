"""WB Promo Calendar API client.

TASK-LEAD-050 — калькулятор рентабельности WB-акций.

WB host: `https://dp-calendar-api.wildberries.ru` (см. WB_API_REFERENCE.md §3).

Endpoints (по публичной документации WB на момент 2026-05-21):
- `GET /api/v1/calendar/promotions` — список акций в окне дат
  (`startDateTime`/`endDateTime` ISO-8601, optional `allPromo=true`)
- `GET /api/v1/calendar/promotions/details` — детали (?promotionIDs=...)
- `GET /api/v1/calendar/promotions/nomenclatures` — товары в акции (?promotionID=)

Лимиты: WB не опубликовал rate-limit на calendar API; используем
осторожный 6/мин с min_interval_s=10s (как для tariffs/documents).

**Graceful fallback:** если WB вернёт 404/410/5xx или token не имеет
прав — функция возвращает пустой список и логирует warning. UI работает
в manual-input режиме (пользователь сам вводит параметры акции).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.integrations.wb.client import WbApiClient, WbApiError, WbCooldownActive
from app.integrations.wb.rate_limiter import TokenBucketLimiter

log = get_logger(__name__)


# WB Promo Calendar host (не входит в стандартный набор `Category` в client.py —
# отдельный лимитер хранится локально; см. _call_calendar()).
_PROMO_BASE = "https://dp-calendar-api.wildberries.ru"
_promo_limiter = TokenBucketLimiter(6, min_interval_s=10.0)


async def list_active_promotions(
    token: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    include_all: bool = True,
) -> list[dict[str, Any]]:
    """Список акций WB в окне дат.

    Args:
        token: WB seller token (tenant-scoped).
        start_date / end_date: окно для фильтра по дате старта акции.
            По умолчанию — текущая дата .. +90 дней.
        include_all: `allPromo=true` — включить уже стартовавшие.

    Returns:
        Список dict'ов с минимально нужными полями:
        ``{id, name, start_date_time, end_date_time, type, participation_pct}``.
        Пустой список при любой ошибке WB (graceful fallback — UI всё равно
        работает в manual-input режиме).
    """
    today = date.today()
    sd = start_date or today
    ed = end_date or date(today.year + (today.month + 2) // 12, ((today.month + 2) % 12) + 1, min(today.day, 28))

    params = {
        "startDateTime": datetime.combine(sd, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        "endDateTime": datetime.combine(ed, datetime.max.time(), tzinfo=timezone.utc).isoformat(),
    }
    if include_all:
        params["allPromo"] = "true"

    try:
        # Используем httpx напрямую с локальным лимитером — host'а нет в стандартной
        # категории клиента (calendar — не statistics/advert/common/etc).
        import httpx

        await _promo_limiter.acquire()
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": token,
                "Accept": "application/json",
                "User-Agent": "RNP-Seller-Service/1.0 (httpx; python)",
            },
        ) as client:
            resp = await client.get(
                f"{_PROMO_BASE}/api/v1/calendar/promotions",
                params=params,
            )
            if resp.status_code == 404:
                log.info("WB Promo Calendar API: 404 (endpoint absent or unavailable)")
                return []
            if resp.status_code == 401 or resp.status_code == 403:
                log.warning(
                    "WB Promo Calendar API: %s — token не имеет прав (нужен Promo-scope)",
                    resp.status_code,
                )
                return []
            if resp.status_code >= 400:
                log.warning(
                    "WB Promo Calendar API: %s — fallback to manual input. Body: %s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
                return []
            data = resp.json() if resp.content else {}

        promotions = data.get("data", {}).get("promotions") if isinstance(data, dict) else None
        if not promotions and isinstance(data, list):
            promotions = data

        out: list[dict[str, Any]] = []
        for p in promotions or []:
            out.append({
                "id": p.get("id") or p.get("ID"),
                "name": p.get("name") or p.get("Name") or "—",
                "start_date_time": p.get("startDateTime") or p.get("StartDateTime"),
                "end_date_time": p.get("endDateTime") or p.get("EndDateTime"),
                "type": p.get("type") or p.get("Type"),
                "in_promo_action": p.get("inPromoAction") or p.get("InPromoAction"),
            })
        return out
    except (WbApiError, WbCooldownActive) as e:
        log.warning("WB Promo Calendar API error: %s — fallback to manual input", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("WB Promo Calendar unexpected error: %s — fallback to manual input", e)
        return []


__all__ = ["list_active_promotions"]
