"""Локальное хранилище фото-вариантов A/B-тестов.

Порт `wbab/src/lib/storage.ts` на Python. Layout файлов сохранён 1:1 ради
data-migration в Phase 7 (rsync wbab/storage → rnp + переписать пути в БД
не придётся).

Структура (под STORAGE_PATH, default /app/storage/photos):
    {abtest_id}/
        {label}{ext}              — главное фото варианта (photo_order=1, legacy-имя)
        {label}_{photo_order}{ext} — дополнительные фото (photo_order ≥ 2)
        __original{ext}           — снапшот главного фото карточки на старте (legacy)
        __original_{photo_order}{ext} — снапшоты всех исходных фото (multi-photo)

Расширения: .jpg/.jpeg/.png/.webp. На WB-Content media ограничения по размеру
(~10 MB на файл, проверять не здесь — выше, в API-валидаторе).

Sync I/O в `asyncio.to_thread` — простой и без зависимостей. Альтернатива
`aiofiles` не нужна: rotation worker — `concurrency=1`, API-handlers пишут
файл размером 1-3 МБ за <50ms, не блокирует loop ощутимо.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

__all__ = [
    "storage_root",
    "abtest_dir",
    "variant_photo_path",
    "save_variant_photo",
    "save_original_photo_order",
    "read_variant_photo",
    "delete_photo_file",
    "delete_abtest_photos",
    "photo_ext_to_mime",
]


def storage_root() -> Path:
    """Корневой каталог фото. Дефолт — `/app/storage/photos` (в Docker).

    Можно переопределить через STORAGE_PATH в .env. Каталог создаётся лениво
    при первой записи; не делаем mkdir на импорте — модуль может загрузиться
    в окружении без прав на FS (например, при alembic offline).
    """
    return Path(os.environ.get("STORAGE_PATH", "/app/storage/photos")).resolve()


def abtest_dir(abtest_id: int) -> Path:
    """Каталог всех фото одного теста."""
    return storage_root() / str(abtest_id)


def variant_photo_path(abtest_id: int, label: str, ext: str, photo_order: int = 1) -> Path:
    """Путь к фото варианта.

    Главное фото (photo_order=1) — `{label}{ext}` для бэк-совместимости с
    легаси-API-роутом storage в wbab. Доп. фото — `{label}_{N}{ext}`.
    """
    ext_norm = _normalize_ext(ext)
    name = f"{label}{ext_norm}" if photo_order == 1 else f"{label}_{photo_order}{ext_norm}"
    return abtest_dir(abtest_id) / name


def original_photo_path(abtest_id: int, photo_order: int, ext: str) -> Path:
    """Путь к снапшоту исходного фото карточки на момент старта теста."""
    ext_norm = _normalize_ext(ext)
    return abtest_dir(abtest_id) / f"__original_{photo_order}{ext_norm}"


def _normalize_ext(ext: str) -> str:
    """Нормализует расширение: `.jpg` ← `JPG` ← `jpg`."""
    ext_l = ext.lower().strip()
    if not ext_l:
        return ".jpg"
    return ext_l if ext_l.startswith(".") else f".{ext_l}"


def _ext_from_filename(original_filename: str) -> str:
    """Достаёт расширение из имени или возвращает .jpg по умолчанию."""
    suffix = Path(original_filename).suffix.lower()
    return suffix if suffix in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"


async def save_variant_photo(
    abtest_id: int,
    label: str,
    photo_order: int,
    file_bytes: bytes,
    original_filename: str,
) -> Path:
    """Сохраняет фото варианта на диск, возвращает путь.

    `photo_order=1` пишется как `{label}{ext}` (legacy-имя для совместимости
    с migrated-data из wbab); ≥2 — как `{label}_{N}{ext}`.
    """
    ext = _ext_from_filename(original_filename)
    path = variant_photo_path(abtest_id, label, ext, photo_order)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)

    await asyncio.to_thread(_write)
    return path


async def save_original_photo_order(
    abtest_id: int,
    photo_order: int,
    file_bytes: bytes,
    ext: str,
) -> Path:
    """Сохраняет снапшот исходной фотографии карточки с конкретным photo_order.

    Используется при первом старте теста — снимаем все фото карточки на WB,
    чтобы при остановке вернуть исходный комплект.
    """
    path = original_photo_path(abtest_id, photo_order, ext)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)

    await asyncio.to_thread(_write)
    return path


async def read_variant_photo(path: str | Path) -> bytes:
    """Читает фото с диска. Бросает FileNotFoundError если файла нет."""
    p = Path(path)
    return await asyncio.to_thread(p.read_bytes)


async def delete_photo_file(path: str | Path) -> None:
    """Удаляет один файл (для удаления фото из paused-теста). Idempotent."""
    p = Path(path)

    def _rm() -> None:
        if p.exists():
            p.unlink()

    await asyncio.to_thread(_rm)


async def delete_abtest_photos(abtest_id: int) -> None:
    """Удаляет ВСЕ фото теста (директорию рекурсивно). Idempotent.

    Вызывается при cascade-удалении теста через DB (DELETE FROM abtest WHERE
    id = ...) — orphan files на диске остались бы без cleanup. Так как в БД
    путь хранится в `abtest_variant_photo.photo_path`, можно было бы пройтись
    по всем строкам; но удалить каталог теста проще и быстрее.
    """
    d = abtest_dir(abtest_id)

    def _rm() -> None:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    await asyncio.to_thread(_rm)


_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def photo_ext_to_mime(ext: str) -> str:
    """`'png'` → `'image/png'`. Неизвестное → `'application/octet-stream'`."""
    return _MIME_MAP.get(_normalize_ext(ext), "application/octet-stream")
