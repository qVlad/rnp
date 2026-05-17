"""A/B test photo uploads — multipart file handling.

Отделён от `api/abtest.py` потому что multipart-handler'ы требуют другую
сигнатуру (UploadFile + Form), и логика валидации/сохранения файлов
не пересекается с CRUD.

Endpoints:
- POST   /api/abtest/{id}/variants/{vid}/photos      — загрузить фото
- DELETE /api/abtest/{id}/variants/{vid}/photos/{pid} — удалить фото
- GET    /api/abtest/{id}/variants/{vid}/photos/{pid} — отдать байты
                                                       (для preview в UI)

Ограничения:
- Размер: до 2 MB на фото (WB Content media лимит ~10 MB, но 2 MB достаточно
  для качественных карточек; защита от случайных RAW из камеры).
- MIME: image/jpeg, image/png, image/webp.
- photo_order: 1..N в рамках варианта (UNIQUE constraint на БД).
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AbTest, AbTestVariant, AbTestVariantPhoto, Product
from app.services.abtest import photo_storage
from app.services.auth import current_brands_filter, get_db_tenant_scoped

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/abtest", tags=["abtest-uploads"])


# WB Content media принимает до ~32 МБ для фото и до ~50 МБ для видео.
# wbab (старый сервис) использовал per-file лимит 256 МБ ради видео-вариантов.
# Берём 256 МБ — покрывает любые WB-валидные форматы с запасом. Дальнейшую
# проверку размера и формата делает WB при `POST /content/v3/media/file`.
MAX_PHOTO_BYTES = 256 * 1024 * 1024  # 256 MB
ALLOWED_MIME = {
    # Фото
    "image/jpeg",
    "image/png",
    "image/webp",
    # Видео (для FUNNEL-тестов с видео-вариантами карточки)
    "video/mp4",
    "video/quicktime",
}


async def _check_variant(
    session: AsyncSession,
    abtest_id: int,
    variant_id: int,
    brands: set[str] | None,
) -> tuple[AbTest, AbTestVariant]:
    test = await session.get(AbTest, abtest_id)
    if test is None:
        raise HTTPException(404, "abtest not found")
    if brands is not None:
        prod = await session.get(Product, test.nm_id)
        if prod is None or (prod.brand or "") not in brands:
            raise HTTPException(403, "test is not in your assigned brands")
    v = await session.get(AbTestVariant, variant_id)
    if v is None or v.abtest_id != abtest_id:
        raise HTTPException(404, "variant not found")
    return test, v


@router.post("/{abtest_id}/variants/{variant_id}/photos")
async def upload_photo(
    abtest_id: int,
    variant_id: int,
    photo_order: Annotated[int, Form(ge=1, le=20)],
    file: Annotated[UploadFile, File()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    test, variant = await _check_variant(session, abtest_id, variant_id, brands)
    if test.status == "running":
        raise HTTPException(400, "pause the test before uploading new photos")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            415, f"content-type {file.content_type!r} not allowed: {sorted(ALLOWED_MIME)}"
        )

    # Stream → bytes (UploadFile.read с size cap).
    body = await file.read(MAX_PHOTO_BYTES + 1)
    if len(body) > MAX_PHOTO_BYTES:
        raise HTTPException(
            413, f"file too large: {len(body)} bytes (max {MAX_PHOTO_BYTES})"
        )

    # Существующее фото на этой позиции — заменяем.
    existing = (
        await session.execute(
            select(AbTestVariantPhoto).where(
                AbTestVariantPhoto.variant_id == variant_id,
                AbTestVariantPhoto.photo_order == photo_order,
            )
        )
    ).scalar_one_or_none()

    path = await photo_storage.save_variant_photo(
        abtest_id=abtest_id,
        label=variant.label,
        photo_order=photo_order,
        file_bytes=body,
        original_filename=file.filename or "photo.jpg",
    )

    if existing is not None:
        # Удалить старый файл если path изменился (другое расширение).
        if str(existing.photo_path) != str(path):
            await photo_storage.delete_photo_file(existing.photo_path)
        existing.photo_path = str(path)
        existing.content_type = file.content_type
    else:
        session.add(
            AbTestVariantPhoto(
                variant_id=variant_id,
                photo_order=photo_order,
                photo_path=str(path),
                content_type=file.content_type,
            )
        )
    await session.flush()
    return {
        "photo_order": photo_order,
        "content_type": file.content_type,
        "size_bytes": len(body),
    }


@router.delete("/{abtest_id}/variants/{variant_id}/photos/{photo_id}")
async def delete_photo(
    abtest_id: int,
    variant_id: int,
    photo_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, str]:
    test, _ = await _check_variant(session, abtest_id, variant_id, brands)
    if test.status == "running":
        raise HTTPException(400, "pause the test before deleting photos")
    p = await session.get(AbTestVariantPhoto, photo_id)
    if p is None or p.variant_id != variant_id:
        raise HTTPException(404, "photo not found")
    await photo_storage.delete_photo_file(p.photo_path)
    await session.delete(p)
    return {"status": "deleted"}


@router.get("/{abtest_id}/variants/{variant_id}/photos/{photo_id}")
async def get_photo_bytes(
    abtest_id: int,
    variant_id: int,
    photo_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
):
    await _check_variant(session, abtest_id, variant_id, brands)
    p = await session.get(AbTestVariantPhoto, photo_id)
    if p is None or p.variant_id != variant_id:
        raise HTTPException(404, "photo not found")
    try:
        data = await photo_storage.read_variant_photo(p.photo_path)
    except FileNotFoundError:
        raise HTTPException(404, "photo file missing on disk")
    return Response(content=data, media_type=p.content_type)
