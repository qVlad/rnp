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
# BUG-DEV-020: 10s между запросами был сверх-осторожным (debug с probe →
# таймаут, страница товаров грузилась медленно). Calendar API спокойно держит
# ~1 req/s. 1.0s — безопасный баланс.
_promo_limiter = TokenBucketLimiter(60, min_interval_s=1.0)


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


async def get_promotion_details(
    token: str, promotion_ids: list[int]
) -> list[dict[str, Any]]:
    """`GET /api/v1/calendar/promotions/details?promotionIDs=...` — детали акций.

    Возвращает `[{id, name, startDateTime, endDateTime, type, discount, ...}]`.
    Graceful fallback на пустой список при 4xx/5xx (TASK-LEAD-155).
    """
    if not promotion_ids:
        return []
    try:
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
                f"{_PROMO_BASE}/api/v1/calendar/promotions/details",
                params={"promotionIDs": [str(pid) for pid in promotion_ids]},
            )
            if resp.status_code in (401, 403, 404):
                log.info(
                    "WB Promo Calendar details: %s (token/route)", resp.status_code
                )
                return []
            if resp.status_code >= 400:
                log.warning(
                    "WB Promo Calendar details: %s body=%s",
                    resp.status_code, (resp.text or "")[:200],
                )
                return []
            data = resp.json() if resp.content else {}
        promotions = (
            data.get("data", {}).get("promotions") if isinstance(data, dict) else None
        )
        if not promotions and isinstance(data, list):
            promotions = data
        return promotions or []
    except (WbApiError, WbCooldownActive) as e:
        log.warning("WB Promo details error: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("WB Promo details unexpected: %s", e)
        return []


async def get_promotion_nomenclatures(
    token: str, promotion_id: int, *, in_action: bool, limit: int = 100
) -> list[dict[str, Any]]:
    """`GET /api/v1/calendar/promotions/nomenclatures` — товары акции.

    BUG-DEV-020: WB требует ОБЯЗАТЕЛЬНЫЕ `inAction` (bool) + `limit` (≤1000) +
    пагинацию `offset` — без них отдаёт пусто/400. `inAction=true` — товары уже
    в акции, `false` — предложенные (можно добавить). WB НЕ возвращает флаг
    inAction внутри item'а, поэтому вызывающая сторона тегирует сама.

    Возвращает «сырые» nomenclature-item'ы WB (нормализация — в
    `api/promo_calculator.get_wb_promotion`). Graceful fallback на [] при ошибке.
    """
    out: list[dict[str, Any]] = []
    offset = 0
    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": token,
                "Accept": "application/json",
                "User-Agent": "RNP-Seller-Service/1.0 (httpx; python)",
            },
        ) as client:
            while True:
                await _promo_limiter.acquire()
                params: dict[str, Any] = {
                    "promotionID": promotion_id,
                    "inAction": "true" if in_action else "false",
                    "limit": limit,
                    "offset": offset,
                }
                resp = await client.get(
                    f"{_PROMO_BASE}/api/v1/calendar/promotions/nomenclatures",
                    params=params,
                )
                if resp.status_code in (401, 403, 404):
                    log.info(
                        "WB Promo nomenclatures: %s (token/route)", resp.status_code
                    )
                    return out
                if resp.status_code >= 400:
                    log.warning(
                        "WB Promo nomenclatures: %s body=%s",
                        resp.status_code, (resp.text or "")[:300],
                    )
                    return out
                data = resp.json() if resp.content else {}

                nomen: Any = None
                if isinstance(data, dict):
                    nomen = data.get("data", {}).get("nomenclatures") or data.get(
                        "nomenclatures"
                    )
                elif isinstance(data, list):
                    nomen = data
                if not isinstance(nomen, list):
                    nomen = []
                out.extend(nomen)
                log.info(
                    "WB Promo nomenclatures promo=%s in_action=%s offset=%s got=%s",
                    promotion_id, in_action, offset, len(nomen),
                )
                if len(nomen) < limit:
                    break
                offset += limit
                if offset > 50000:  # safety-стоп от бесконечного цикла
                    break
        return out
    except (WbApiError, WbCooldownActive) as e:
        log.warning("WB Promo nomenclatures error: %s", e)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("WB Promo nomenclatures unexpected: %s", e)
        return out


async def debug_nomenclatures_raw(
    token: str, promotion_id: int, *, in_action: bool, limit: int = 1000
) -> dict[str, Any]:
    """Диагностика: сырой ответ WB nomenclatures (BUG-DEV-020).

    Возвращает HTTP-статус, фрагмент тела, и — если распарсилось — верхние
    ключи объекта и ключи первого item'а. Нужен чтобы увидеть реальную
    структуру WB для автоакций (а не гадать). Используется в endpoint'е
    `/wb-promotions/{id}?debug=1`.
    """
    info: dict[str, Any] = {
        "in_action": in_action,
        "status": None,
        "body_snippet": None,
        "top_level_keys": None,
        "first_item_keys": None,
        "parsed_count": 0,
    }
    try:
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
                f"{_PROMO_BASE}/api/v1/calendar/promotions/nomenclatures",
                params={
                    "promotionID": promotion_id,
                    "inAction": "true" if in_action else "false",
                    "limit": limit,
                    "offset": 0,
                },
            )
            info["status"] = resp.status_code
            text = resp.text or ""
            info["body_snippet"] = text[:600]
            try:
                data = resp.json() if resp.content else {}
            except Exception:  # noqa: BLE001
                return info
        if isinstance(data, dict):
            info["top_level_keys"] = list(data.keys())
            nomen = data.get("data", {}).get("nomenclatures") or data.get(
                "nomenclatures"
            )
            if isinstance(nomen, list):
                info["parsed_count"] = len(nomen)
                if nomen and isinstance(nomen[0], dict):
                    info["first_item_keys"] = list(nomen[0].keys())
        elif isinstance(data, list):
            info["parsed_count"] = len(data)
            if data and isinstance(data[0], dict):
                info["first_item_keys"] = list(data[0].keys())
                info["top_level_keys"] = "(top-level array)"
    except Exception as e:  # noqa: BLE001
        info["body_snippet"] = f"EXC: {e}"
    return info


async def probe_nomenclatures_params(
    token: str, promotion_id: int
) -> list[dict[str, Any]]:
    """Перебор вариантов параметров nomenclatures (BUG-DEV-020 probe).

    WB отдаёт 422 на `{promotionID, inAction, limit, offset}` для автоакций.
    Пробуем разные комбинации, чтобы найти принимаемую. Возвращает список
    `{params, status, body, count}` — смотрим какая даёт 200 с данными.
    """
    combos: list[dict[str, Any]] = [
        {"promotionID": promotion_id},
        {"promotionID": promotion_id, "inAction": "true"},
        {"promotionID": promotion_id, "inAction": "false"},
        {"promotionID": promotion_id, "limit": 100},
        {"promotionID": promotion_id, "inAction": "true", "limit": 100},
        {"promotionID": promotion_id, "inAction": "true", "limit": 100, "offset": 0},
        {"promotionID": promotion_id, "inAction": "true", "limit": 1000},
        # camelCase id-варианты на случай иного контракта
        {"id": promotion_id, "inAction": "true", "limit": 100},
        {"promotionId": promotion_id, "inAction": "true", "limit": 100},
    ]
    out: list[dict[str, Any]] = []
    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": token,
                "Accept": "application/json",
                "User-Agent": "RNP-Seller-Service/1.0 (httpx; python)",
            },
        ) as client:
            for params in combos:
                rec: dict[str, Any] = {"params": params, "status": None, "body": None, "count": 0}
                try:
                    await _promo_limiter.acquire()
                    resp = await client.get(
                        f"{_PROMO_BASE}/api/v1/calendar/promotions/nomenclatures",
                        params=params,
                    )
                    rec["status"] = resp.status_code
                    rec["body"] = (resp.text or "")[:160]
                    if resp.status_code < 400 and resp.content:
                        data = resp.json()
                        nomen = None
                        if isinstance(data, dict):
                            nomen = data.get("data", {}).get(
                                "nomenclatures"
                            ) or data.get("nomenclatures")
                        elif isinstance(data, list):
                            nomen = data
                        rec["count"] = len(nomen) if isinstance(nomen, list) else 0
                except Exception as e:  # noqa: BLE001
                    rec["body"] = f"EXC: {e}"
                out.append(rec)
    except Exception as e:  # noqa: BLE001
        out.append({"params": "client-init", "body": f"EXC: {e}"})
    return out


__all__ = [
    "list_active_promotions",
    "get_promotion_details",
    "get_promotion_nomenclatures",
    "debug_nomenclatures_raw",
    "probe_nomenclatures_params",
]
