"""Fernet шифрование для секретов хранящихся в БД (WB-токены).

**Зачем:** если БД утечёт (бэкап, дамп, SQL-injection, скриншот pgAdmin) —
plaintext WB-токены дадут злоумышленнику полный доступ к WB-кабинетам всех
клиентов сервиса. Fernet шифрует их symmetric-AES'ом; ключ хранится в
`.env`, отдельно от БД.

**Ключ:** `SECRETS_ENCRYPTION_KEY` в `.env` — URL-safe base64 32 байта.
Сгенерировать: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**Fallback:** если ключ не задан — шифрование отключено (токены лежат
plaintext). Это нужно для миграции с legacy-установки: ставим ключ →
сервис при старте проходит по всем tenants и шифрует существующие
токены (см. `migrate_plaintext_tokens()` в lifespan).

**Формат:** зашифрованные токены сохраняются с префиксом `enc:` чтобы
отличать от plaintext. При чтении: если префикс есть → decrypt, нет →
вернуть как есть (legacy).
"""
from __future__ import annotations

import base64
import os
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

from app.core.logging import get_logger

log = get_logger(__name__)

_PREFIX: Final[str] = "enc:"


def _get_key() -> bytes | None:
    """Прочитать ключ из ENV. Возвращает bytes (Fernet) или None."""
    raw = os.environ.get("SECRETS_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        # Валидация — Fernet требует 32 байт base64.
        base64.urlsafe_b64decode(raw)
        return raw.encode()
    except Exception as e:  # noqa: BLE001
        log.warning("SECRETS_ENCRYPTION_KEY invalid (%s) — encryption disabled", e)
        return None


_KEY_CACHE: bytes | None = None
_CACHED: bool = False


def _fernet() -> Fernet | None:
    """Lazy-singleton: создаём Fernet один раз."""
    global _KEY_CACHE, _CACHED
    if not _CACHED:
        _KEY_CACHE = _get_key()
        _CACHED = True
    if _KEY_CACHE is None:
        return None
    return Fernet(_KEY_CACHE)


def encrypt(value: str | None) -> str | None:
    """Зашифровать. Если ключ не задан — вернуть plaintext (с warning).
    Если value пустой — None."""
    if not value:
        return None
    f = _fernet()
    if f is None:
        log.warning(
            "SECRETS_ENCRYPTION_KEY not set — saving secret as plaintext. "
            "Generate a key: python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
        return value
    if value.startswith(_PREFIX):
        return value  # Уже зашифровано — двойного шифрования не делаем.
    encrypted = f.encrypt(value.encode("utf-8")).decode("ascii")
    return _PREFIX + encrypted


def decrypt(value: str | None) -> str | None:
    """Расшифровать. Если у строки нет префикса `enc:` — вернуть как есть
    (legacy plaintext). Если ключ не настроен но префикс есть — error."""
    if not value:
        return None
    if not value.startswith(_PREFIX):
        return value  # Legacy plaintext.
    raw = value[len(_PREFIX):]
    f = _fernet()
    if f is None:
        log.error(
            "Cannot decrypt: SECRETS_ENCRYPTION_KEY not set, but secret has "
            "'enc:' prefix. Restoring the key is required."
        )
        return None
    try:
        return f.decrypt(raw.encode("ascii")).decode("utf-8")
    except InvalidToken:
        log.error(
            "Cannot decrypt: SECRETS_ENCRYPTION_KEY mismatch (was the key "
            "rotated without re-encrypting?). Tenant data inaccessible."
        )
        return None


async def migrate_plaintext_tokens() -> int:
    """Найти все plaintext WB-токены в БД и зашифровать на месте.

    Вызывается из FastAPI lifespan после установки ключа. Идемпотентно:
    повторный запуск — no-op, т.к. encrypt() игнорирует строки с префиксом.
    Возвращает кол-во зашифрованных токенов.
    """
    if _fernet() is None:
        return 0
    from sqlalchemy import select  # noqa: WPS433

    from app.db.models import Tenant  # noqa: WPS433
    from app.db.session import session_scope  # noqa: WPS433

    n = 0
    async with session_scope() as s:
        rows = (await s.execute(select(Tenant))).scalars().all()
        for tenant in rows:
            if tenant.wb_token and not tenant.wb_token.startswith(_PREFIX):
                tenant.wb_token = encrypt(tenant.wb_token)
                n += 1
        if n:
            log.info("Encrypted %d plaintext WB-tokens", n)
    return n
