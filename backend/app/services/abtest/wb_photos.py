"""Подгрузка текущих фото карточки с WB для использования как Вариант A.

При создании A/B-теста удобно взять текущую воронку фото с WB-карточки и
сделать её базой сравнения (Вариантом A) — пользователь грузит только
новые версии (B/C/D). Это в 2x ускоряет настройку и убирает «загрузил
сам себе текущее как тест» класс ошибок.

Flow:
1. `fetch_current_photo_urls(wb, nm_id, count)` — через
   `content_media.get_card_by_nm_id` находим карточку, выдёргиваем
   `photos[].big` (URL'ы в WB CDN). Возвращаем до `count` штук.
2. `download_photos_for_variant(session, abtest_id, variant_id, urls)` —
   скачиваем каждый URL httpx'ом, сохраняем в storage через
   `photo_storage.save_variant_photo`, пишем `abtest_variant_photo` строку.

Картинки с WB CDN отдаются как WebP (нет аутентификации, размер до ~600KB).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.db.models import AbTestVariant, AbTestVariantPhoto
from app.integrations.wb.client import WbApiClient
from app.integrations.wb.content_media import get_card_by_nm_id
from app.services.abtest import photo_storage
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

__all__ = [
    "fetch_current_photo_urls",
    "download_photos_for_variant",
]


def _extract_photo_urls(card: dict[str, Any], count: int) -> list[str]:
    """Из ответа `cards/list` достаём URL'ы первых N фото в максимальном
    размере. WB кладёт каждое фото как объект `{"big": "...", "c516x688": "...",
    "c246x328": "..."}`. Берём `big` (нативное разрешение), fallback на
    c516x688.
    """
    photos = card.get("photos") or []
    out: list[str] = []
    for p in photos[:count]:
        if not isinstance(p, dict):
            continue
        url = p.get("big") or p.get("c516x688") or p.get("c246x328")
        if isinstance(url, str) and url.startswith("http"):
            out.append(url)
    return out


async def fetch_current_photo_urls(
    wb: WbApiClient,
    nm_id: int,
    count: int = 10,
) -> list[str]:
    """Возвращает до `count` URL'ов текущих фото карточки.

    Может занять до 2 минут — `get_card_by_nm_id` пагинирует list-cards
    (100 за раз × до 20 страниц). На практике карточки укладываются в
    1-2 страницы. На любую ошибку возвращает пустой список — caller
    показывает понятное сообщение.
    """
    if count < 1:
        return []
    try:
        card = await get_card_by_nm_id(wb, nm_id)
    except Exception as e:
        log.warning("fetch_current_photo_urls(%d): WB lookup failed: %s", nm_id, e)
        return []
    if not card:
        return []
    return _extract_photo_urls(card, count)


async def download_photos_for_variant(
    session: AsyncSession,
    abtest_id: int,
    variant_id: int,
    variant_label: str,
    urls: list[str],
) -> int:
    """Скачивает каждый URL и создаёт `abtest_variant_photo` строку.

    Возвращает число успешно загруженных. Ошибки на отдельные URL'ы
    логируются, но не валят всю операцию (если из 10 фото скачались
    8 — это ОК, тест запустится с тем что есть; пользователь увидит
    превью и сможет дозагрузить остальное).
    """
    if not urls:
        return 0

    saved = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for i, url in enumerate(urls, start=1):
            try:
                resp = await client.get(url)
                if resp.status_code != 200 or not resp.content:
                    log.warning(
                        "download_photos_for_variant: url[%d]=%s status=%d",
                        i, url, resp.status_code,
                    )
                    continue
                # MIME из заголовка WB CDN или fallback на webp.
                ctype = resp.headers.get("content-type", "image/webp").split(";")[0].strip()
                # Расширение из URL'а — у WB всегда `.webp` или `.jpg`.
                ext = Path(url.split("?")[0]).suffix.lower() or ".webp"
                path = await photo_storage.save_variant_photo(
                    abtest_id=abtest_id,
                    label=variant_label,
                    photo_order=i,
                    file_bytes=resp.content,
                    original_filename=f"wb-current{ext}",
                )
                session.add(
                    AbTestVariantPhoto(
                        variant_id=variant_id,
                        photo_order=i,
                        photo_path=str(path),
                        content_type=ctype,
                    )
                )
                saved += 1
            except Exception as e:
                log.warning(
                    "download_photos_for_variant: url[%d]=%s failed: %s",
                    i, url, e,
                )
    return saved
