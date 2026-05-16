"""WB Content API — фото-операции карточки (для A/B-ротации).

Эти endpoint'ы добавлены ради A/B-тестирования: ротация заменяет главное
(и опционально дополнительные) фото карточки одного из вариантов теста.

Endpoints:
- POST /content/v3/media/file  — загрузка фото бинарником (multipart) на
                                  конкретную позицию (header X-Photo-Number).
                                  Synchronous: успех = байты приняты WB.
- POST /content/v3/media/save  — установка фото по списку URL (асинхронно у WB).
                                  Дешевле когда нужно «вернуть исходное» (URL
                                  у нас уже есть в abtest.original_photos).
- helper get_card_by_nm_id()   — поиск карточки через listCards-пагинацию.
                                  Нужен чтобы получить актуальный URL фото
                                  ПОСЛЕ ротации для детекции ручных правок.

⚠ Rate limit: media endpoints ~10 req/min (WB_API_REFERENCE.md §3 — отдельный
от cards/list лимит на тот же host). Категория client'а — "content" с общим
limiter'ом 60/min. На уровне Celery worker для ротации concurrency=1 + sleep
~7 сек между фото эффективно ограничивает burst до ~8 req/min. Если когда-
нибудь потребуется тонкий контроль — выделить категорию `content_media` с
TokenBucketLimiter(10, min_interval_s=6.0).
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.integrations.wb.client import WbApiClient
from app.integrations.wb.content import fetch_cards_list

log = get_logger(__name__)


async def upload_media_file(
    client: WbApiClient,
    nm_id: int,
    photo_number: int,
    file_bytes: bytes,
    filename: str,
    content_type: str = "image/jpeg",
) -> dict[str, Any] | None:
    """`POST /content/v3/media/file` — загрузка фото бинарником на позицию.

    Параметры:
        nm_id        — артикул WB карточки
        photo_number — 1..N, позиция фото (1 = главное)
        file_bytes   — содержимое файла
        filename     — имя файла (для multipart, не сохраняется у WB)
        content_type — MIME type (image/jpeg|png|webp). По умолчанию jpeg.

    Возвращает body ответа WB (обычно `{"data": null, "error": false, ...}`).
    На любую ошибку выбрасывает `WbApiError` — caller (rotation worker)
    решает, лог-варнинг или fail задачу.

    Headers:
        Authorization: <token>       — добавляется client'ом
        X-Nm-Id: <nm_id>             — обязателен
        X-Photo-Number: <photo_number> — обязателен
    Body: multipart/form-data, поле `uploadfile`.
    """
    return await client.post(
        "/content/v3/media/file",
        category="content",
        files={"uploadfile": (filename, file_bytes, content_type)},
        extra_headers={
            "X-Nm-Id": str(nm_id),
            "X-Photo-Number": str(photo_number),
        },
    )


async def save_media_by_url(
    client: WbApiClient,
    nm_id: int,
    media_urls: list[str],
) -> dict[str, Any] | None:
    """`POST /content/v3/media/save` — установка фото-комплекта по URL (async у WB).

    Используется чтобы быстро «вернуть исходное» при остановке теста — URL'ы
    оригинальных фото сохранены в `abtest.original_photos`. Дешевле бинарной
    загрузки: один запрос вместо N.

    Параметры:
        nm_id      — артикул карточки
        media_urls — список абсолютных URL (порядок = photo_order, 1-based)

    WB обрабатывает асинхронно: успешный ответ = принято в очередь, фактическая
    замена на карточке появится через 1-5 минут.
    """
    return await client.post(
        "/content/v3/media/save",
        category="content",
        json={"nmId": nm_id, "data": media_urls},
    )


async def get_card_by_nm_id(
    client: WbApiClient,
    nm_id: int,
    *,
    max_pages: int = 20,
) -> dict[str, Any] | None:
    """Найти карточку по `nm_id` через постраничный `listCards`.

    WB не даёт «достань карточку по nm_id», только постраничный список с
    сортировкой по `updatedAt`. Перебираем максимум `max_pages × 100` карточек
    (по умолчанию 2000 — хватит на любого селлера; ленты товаров > 2000
    редки). Если не нашли — `None`.

    Используется для:
    - Сохранения `original_photos` при старте теста.
    - Детекции ручных правок: после ротации проверяем `photos[0].big` vs
      `wb_photo_url_after` в `abtest_rotation`. Расходятся → пользователь
      правил карточку вручную → создаём `abtest_alert`.
    """
    page_idx = 0
    async for cards_page in fetch_cards_list(client, limit=100):
        page_idx += 1
        for card in cards_page:
            if int(card.get("nmID") or 0) == nm_id:
                return card
        if page_idx >= max_pages:
            log.warning(
                "get_card_by_nm_id(%d): exhausted %d pages, card not found",
                nm_id, max_pages,
            )
            break
    return None
