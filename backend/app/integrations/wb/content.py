"""WB Content API — карточки товаров (только для photo_url enrichment).

Используем единственный endpoint: `POST /content/v2/get/cards/list`.
Возвращает список карточек с полями `nmID`, `photos` (массив URL разных
размеров), `vendorCode`, `subjectName`, `brand` и др.

Для нашей задачи интересен только `photos[0].big` (URL основной картинки).
Сохраняем его в `products.photo_url`, чтобы фото-прокси не перебирал
basket-CDN'ы при каждом cold MISS (~700мс) — берёт сразу нужный URL."""
from __future__ import annotations

from typing import Any, Iterable

from app.integrations.wb.client import WbApiClient


async def fetch_cards_list(
    client: WbApiClient,
    *,
    limit: int = 100,
    locale: str = "ru",
) -> Iterable[list[dict[str, Any]]]:
    """Постранично выгружает карточки продавца. Yield-ом возвращает страницы
    (списки карточек) — кладём в БД сразу batch'ами, не держим всё в памяти.

    Pagination: cursor с полями `updatedAt` + `nmID` из последней карточки
    предыдущей страницы. WB возвращает `cursor.total < limit` когда страница
    последняя.

    `limit` максимум 100 (WB API). По доке лимит до 100 карточек за запрос.
    """
    cursor: dict[str, Any] = {"limit": limit}
    while True:
        body = {
            "settings": {
                "cursor": cursor,
                "filter": {"withPhoto": -1},  # все карточки (с фото или без)
            }
        }
        data = await client.post(
            "/content/v2/get/cards/list",
            category="content",
            json=body,
        )
        cards: list[dict[str, Any]] = (data or {}).get("cards") or []
        if not cards:
            return
        yield cards
        c = (data or {}).get("cursor") or {}
        # Последняя страница: WB возвращает total < limit (или 0).
        total = int(c.get("total") or 0)
        if total < limit:
            return
        # Курсор для следующей страницы — updatedAt + nmID последней карточки.
        cursor = {
            "limit": limit,
            "updatedAt": c.get("updatedAt") or cards[-1].get("updatedAt"),
            "nmID": c.get("nmID") or cards[-1].get("nmID"),
        }


def extract_photo_url(card: dict[str, Any]) -> str | None:
    """Возвращает URL «big» фото первой картинки карточки (или None если нет).

    Структура `card["photos"]`: `[{"big": "...", "c246x328": "...", ...}, ...]`.
    Берём первое фото, размер `big` (наибольший)."""
    photos = card.get("photos") or []
    if not photos:
        return None
    first = photos[0] or {}
    url = first.get("big") or first.get("c516x688") or first.get("c246x328")
    return url if isinstance(url, str) and url else None


def extract_dimensions_volume_l(card: dict[str, Any]) -> "Decimal | None":
    """Возвращает объём карточки в литрах из `dimensions` WB Content API.

    Структура WB: `card["dimensions"]: {"length": 30, "width": 20, "height": 5}`
    — это габариты в **сантиметрах**. Объём = L × W × H / 1000 → литры.

    Для UNIT-плана это используется в формулах логистики/хранения (см.
    `UNIT_PLAN.md` §4). Если хотя бы одно измерение отсутствует или 0 —
    возвращает None.
    """
    from decimal import Decimal as _D

    dims = card.get("dimensions") or {}
    if not isinstance(dims, dict):
        return None
    try:
        l = float(dims.get("length") or 0)
        w = float(dims.get("width") or 0)
        h = float(dims.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if l <= 0 or w <= 0 or h <= 0:
        return None
    vol_cm3 = l * w * h
    vol_l = vol_cm3 / 1000.0
    # Округляем до 3 знаков (NUMERIC(8,3) в products.volume_l).
    return _D(f"{vol_l:.3f}")
