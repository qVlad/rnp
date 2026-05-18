"""Onboarding-скрипт для нового managed-клиента.

Создаёт нового tenant'а + первого director-юзера + (опционально) WB-токен +
заводит записи в `tenant_modules` (`core=ON`, остальные по флагам). Идемпотентен
по `slug` — если tenant уже существует, проверяет наличие director'а и модулей,
не дубликатит.

Решение собственника от 2026-05-17: managed-hosting сначала. Этот скрипт —
единственный способ создания нового tenant'а до перехода в SaaS (тогда добавим
публичный /api/auth/signup как replacement).

Usage::

    docker compose exec backend python -m scripts.onboard_managed_tenant \\
        --slug acme \\
        --name "ACME LLC" \\
        --director-username acme_director \\
        --director-password "secure_pwd_here" \\
        --director-full-name "Иван Петров" \\
        [--wb-token "$WB_TOKEN"] \\
        [--enable-modules chargebacks,audit_mode] \\
        [--dry-run]

После выполнения:
- Tenant создан (id = autoincrement, slug = unique)
- Director-юзер создан с bcrypt-хэшем пароля (роль `director`)
- `tenant_modules.core` = enabled (всегда)
- Опциональные модули из `--enable-modules` = enabled
- Если передан WB-токен — сохранён (но без валидации; валидация при первом
  WB-запросе)

⚠ Этот скрипт НЕ требует web-UI и не делает HTTP-вызовов — работает напрямую
с БД. Это нужно для bootstrap-сценария когда web ещё не готов или закрыт.

См. OPERATIONS.md раздел «Подключение нового managed-клиента» для процедуры
ops (бэкап + запуск + smoke + передача доступа клиенту).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging, get_logger
from app.db.models import Tenant, TenantModule, User
from app.db.session import SessionLocal as async_session_maker
from app.services.feature_flags import ALWAYS_ENABLED, KNOWN_MODULES

log = get_logger(__name__)


async def _get_or_create_tenant(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    wb_token: str | None,
) -> Tenant:
    existing = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if existing:
        log.info("tenant %s already exists (id=%d), skipping create", slug, existing.id)
        # Не перезаписываем токен — это могло бы потерять валидированный токен.
        return existing
    tenant = Tenant(slug=slug, name=name, wb_token=wb_token)
    session.add(tenant)
    await session.flush()  # ensure id is populated
    log.info("created tenant %s (id=%d)", slug, tenant.id)
    return tenant


async def _get_or_create_director(
    session: AsyncSession,
    *,
    tenant_id: int,
    username: str,
    password: str,
    full_name: str | None,
) -> User:
    existing = (
        await session.execute(
            select(User).where(
                User.tenant_id == tenant_id, User.username == username
            )
        )
    ).scalar_one_or_none()
    if existing:
        log.info(
            "user %s already exists in tenant %d (id=%d), skipping",
            username,
            tenant_id,
            existing.id,
        )
        return existing
    pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(
        tenant_id=tenant_id,
        username=username,
        password_hash=pwd_hash,
        role="director",
        full_name=full_name,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    log.info("created director user %s (id=%d) in tenant %d", username, user.id, tenant_id)
    return user


async def _seed_modules(
    session: AsyncSession,
    *,
    tenant_id: int,
    enable_extra: set[str],
) -> None:
    """Заводит записи в tenant_modules для всех KNOWN_MODULES.

    `core` — всегда enabled. `enable_extra` — дополнительные коды которые
    нужно включить сразу. Остальные — enabled=false, но запись создаётся
    чтобы фронт мог их отображать в /settings.
    """
    existing_codes = set(
        (
            await session.execute(
                select(TenantModule.module_code).where(
                    TenantModule.tenant_id == tenant_id
                )
            )
        ).scalars().all()
    )

    now = datetime.now(timezone.utc)
    created = 0
    for code in sorted(KNOWN_MODULES):
        if code in existing_codes:
            continue
        is_core = code in ALWAYS_ENABLED
        should_enable = is_core or (code in enable_extra)
        session.add(
            TenantModule(
                tenant_id=tenant_id,
                module_code=code,
                enabled=should_enable,
                enabled_at=now if should_enable else None,
                notes="seeded by onboard_managed_tenant.py",
            )
        )
        created += 1
        if should_enable:
            log.info("module %s enabled for tenant %d", code, tenant_id)
    if created:
        log.info("seeded %d module rows for tenant %d", created, tenant_id)


async def main(args: argparse.Namespace) -> None:
    configure_logging()

    unknown_modules = set(args.enable_modules) - KNOWN_MODULES
    if unknown_modules:
        raise SystemExit(
            f"Unknown modules requested: {sorted(unknown_modules)}. "
            f"Allowed: {sorted(KNOWN_MODULES)}"
        )

    async with async_session_maker() as session:
        if args.dry_run:
            log.info("DRY RUN — no changes will be committed")

        tenant = await _get_or_create_tenant(
            session,
            slug=args.slug,
            name=args.name,
            wb_token=args.wb_token,
        )
        await _get_or_create_director(
            session,
            tenant_id=tenant.id,
            username=args.director_username,
            password=args.director_password,
            full_name=args.director_full_name,
        )
        await _seed_modules(
            session,
            tenant_id=tenant.id,
            enable_extra=set(args.enable_modules),
        )

        if args.dry_run:
            await session.rollback()
            log.info("DRY RUN done — rolled back")
        else:
            await session.commit()
            log.info("✓ onboarding complete: tenant=%s id=%d", tenant.slug, tenant.id)
            log.info(
                "  Login as %s with the given password at the web UI.",
                args.director_username,
            )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", required=True, help="URL-safe идентификатор tenant'а")
    p.add_argument("--name", required=True, help="Отображаемое имя компании")
    p.add_argument("--director-username", required=True)
    p.add_argument("--director-password", required=True)
    p.add_argument("--director-full-name", default=None)
    p.add_argument("--wb-token", default=None, help="WB API token (опционально — можно ввести позже через UI)")
    p.add_argument(
        "--enable-modules",
        default="",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        help="Список модулей через запятую, например chargebacks,audit_mode",
    )
    p.add_argument("--dry-run", action="store_true", help="Не коммитить — только показать что будет сделано")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(_parse_args()))
