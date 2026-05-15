"""WB Jam — поисковые запросы по карточкам (платная подписка).

Точный endpoint WB не задокументирован публично; распределение endpoint'ов
для аналитики по поисковым запросам в WB API менялось за последние годы.
Текущий приоритетный кандидат — `/api/v2/search-report/...` на
`seller-analytics-api.wildberries.ru` (категория 'analytics' уже настроена).

Если URL не сработает — пользователь может переопределить через Settings
(`wb_jam_url_template`); fetcher подставит nm_id и даты в шаблон.

Защитные механизмы:
  - Любая 4xx-ошибка возвращает [] (sync помечает чекпоинт `skipped`).
  - 401/403 — логируем как «нужно проверить scope/подписку».
  - Rate-limit: используем категорию analytics (3/мин, 20с между).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.integrations.wb.client import WbApiClient, WbApiError


log = logging.getLogger(__name__)


# Дефолтные кандидаты endpoint'ов (пробуем по порядку при отсутствии явной настройки).
# Когда WB опубликует точный — обновить, или юзер задаст явно через Settings.
_DEFAULT_CANDIDATES: list[tuple[str, str]] = [
    # (path, category)
    ("/api/v2/search-report/products", "analytics"),
    ("/api/v2/search-report", "analytics"),
    ("/content/v3/keywords/search-report", "content"),
]


async def fetch_jam_for_nm(
    client: WbApiClient,
    *,
    nm_id: int,
    date_from: date,
    date_to: date,
    limit: int = 30,
    custom_path: str | None = None,
    custom_category: str = "analytics",
) -> list[dict[str, Any]]:
    """Достать ТОП-N поисковых запросов для конкретной карточки за период.

    Возвращает список словарей с произвольной структурой WB. Маппинг
    в `JamQuery` делается в sync-таске.

    `custom_path` — если задан в настройках, пробуем только его; иначе
    пробуем дефолтные кандидаты по порядку до первого успеха.
    """
    body = {
        "period": {
            "begin": date_from.isoformat(),
            "end": date_to.isoformat(),
        },
        "nmIDs": [nm_id],
        "topOrderBy": "openCard",
        "orderBy": {"field": "openCard", "mode": "desc"},
        "limit": limit,
    }

    candidates = (
        [(custom_path, custom_category)] if custom_path else list(_DEFAULT_CANDIDATES)
    )

    last_err: WbApiError | None = None
    for path, category in candidates:
        try:
            data = await client.post(path, category=category, json=body)
        except WbApiError as e:
            last_err = e
            # 404 — endpoint не существует на этом хосте; пробуем следующий
            if e.status == 404:
                log.info("jam: endpoint %s returned 404 — trying next candidate", path)
                continue
            # 401/403 — токен валиден, но нет scope для Jam → пробрасываем
            if e.status in (401, 403):
                log.warning(
                    "jam: %s returned %d — scope/subscription issue; bailing out",
                    path, e.status,
                )
                raise
            # 429 / 5xx — пробрасываем (sync таска retry'нёт)
            raise
        # data может быть list или dict с ключом data/items/cards
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("data", "items", "products", "cards"):
                v = data.get(k)
                if isinstance(v, list):
                    return v
            # объект не похож на ожидаемый — возвращаем как есть в одной обёртке
            return [data]
        return []
    # Все кандидаты дали 404
    if last_err:
        log.warning("jam: all endpoint candidates failed (last %d %s)", last_err.status, last_err)
    return []


def normalize_jam_row(
    raw: dict[str, Any], *, nm_id: int, period_start: date, period_end: date
) -> dict[str, Any] | None:
    """Преобразовать сырую WB-запись в формат для `upsert_jam_query`.

    WB может прислать разные имена полей в зависимости от endpoint:
      - `text` / `query` / `keyword` / `searchText`
      - `orderCount` / `orders` / `nmOrders`
      - `clickCount` / `clicks`
      - `viewCount` / `views` / `openCard` / `impressions`
      - `adSum` / `adSpent` / `cost`

    Если ничего из этого нет — None (skip).
    """
    # query
    q = (
        raw.get("text")
        or raw.get("query")
        or raw.get("keyword")
        or raw.get("searchText")
        or raw.get("name")
    )
    if not q or not isinstance(q, str):
        return None
    return {
        "nm_id": nm_id,
        "query": q.strip()[:512],
        "period_start": period_start,
        "period_end": period_end,
        "orders": int(
            raw.get("orderCount")
            or raw.get("orders")
            or raw.get("nmOrders")
            or 0
        ),
        "clicks": int(
            raw.get("clickCount") or raw.get("clicks") or 0
        ),
        "views": int(
            raw.get("viewCount")
            or raw.get("views")
            or raw.get("openCard")
            or raw.get("impressions")
            or 0
        ),
        "ad_spent": float(
            raw.get("adSum") or raw.get("adSpent") or raw.get("cost") or 0
        ),
    }
