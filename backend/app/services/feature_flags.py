"""Feature flags per-tenant — модульная разработка / включение фич без релизов.

См. STRATEGY_COCKPIT §7.1 и `agents/references/market/top-features-2026-05-17.md`
Tech #3 (Feature flags). Решение собственника от 2026-05-17: managed-hosting
сначала — поэтому без `expires_at` / subscription_status / биллинга. Это будет
в v2 при переходе на SaaS.

## Использование

В роутере новой product-фичи (chargebacks / audit / redistribution / …):

```python
from app.services.feature_flags import require_module

router = APIRouter(
    prefix="/api/chargebacks",
    dependencies=[Depends(require_module("chargebacks"))],
)
```

Юзер с выключённым модулем получает 403 с подсказкой обратиться к
администратору (managed-hosting кейс) или к биллингу (когда переедем в SaaS).

## Список модулей (canonical)

| Code | Описание | Default |
|---|---|---|
| `core` | Базовые экраны (дашборд / P&L / units / supply / opex) | Всегда ON |
| `chargebacks` | Лента списаний WB + workflow оспаривания | OFF, опц. |
| `audit_mode` | 3-source reconciliation (наш P&L ↔ WB ↔ бухгалтер) | OFF |
| `redistribution` | Перераспределение остатков + ROI | OFF |
| `bidder` | Биддер lite (rule-based) | OFF (Фаза 4+) |
| `reviews` | Отзывы и вопросы + AI-ответы | OFF (Фаза 2) |
| `card_ab` | A/B тесты карточек (фото/цена) | OFF |
| `seo` | SEO-позиции + jam-кластеры | OFF |

Базовый `core` — `is_always_enabled` ниже. Остальные — через таблицу
`tenant_modules`. Добавление нового кода: вписать в `KNOWN_MODULES` и пройти
`onboard_managed_tenant.py` чтобы новые tenant'ы получили его в OFF.
"""
from __future__ import annotations

from typing import Final

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantModule
from app.services.auth import CurrentUser, get_current_user
from app.db.session import get_db


# Модули которые ВСЕГДА доступны (нельзя отключить — иначе сервис непригоден).
ALWAYS_ENABLED: Final = frozenset({"core"})


# Канонический список модулей. Расширять по мере добавления product-фич.
# При вписывании нового модуля — также обновить onboard_managed_tenant.py
# чтобы свежие tenant'ы получали запись (enabled=false) при создании.
KNOWN_MODULES: Final = frozenset(
    {
        "core",
        "chargebacks",
        "audit_mode",
        "redistribution",
        "bidder",
        "reviews",
        "card_ab",
        "seo",
    }
)


async def is_module_enabled(
    session: AsyncSession,
    tenant_id: int,
    module_code: str,
) -> bool:
    """Read-only проверка: включён ли модуль для tenant'а.

    Используй когда нужно «мягкое» поведение — например, прятать пункт меню
    без 403. Для жёсткого guard'а — `require_module()`.
    """
    if module_code in ALWAYS_ENABLED:
        return True
    row = (
        await session.execute(
            select(TenantModule.enabled).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.module_code == module_code,
            )
        )
    ).scalar_one_or_none()
    return bool(row)


async def list_modules(
    session: AsyncSession,
    tenant_id: int,
) -> dict[str, bool]:
    """Возвращает { module_code: enabled } для всех KNOWN_MODULES.

    Используется фронтом чтобы скрыть/показать пункты меню. Модули, для которых
    нет записи в БД, считаются OFF (кроме `ALWAYS_ENABLED`).
    """
    rows = (
        await session.execute(
            select(TenantModule.module_code, TenantModule.enabled).where(
                TenantModule.tenant_id == tenant_id
            )
        )
    ).all()
    by_code = {r.module_code: bool(r.enabled) for r in rows}
    return {
        code: True if code in ALWAYS_ENABLED else by_code.get(code, False)
        for code in KNOWN_MODULES
    }


def require_module(module_code: str):
    """FastAPI dependency — 403 если модуль не включён для текущего tenant'а.

    Usage::

        router = APIRouter(
            prefix="/api/chargebacks",
            dependencies=[Depends(require_module("chargebacks"))],
        )

    `core` всегда включён — нет смысла на него вешать guard.
    Module-code не из `KNOWN_MODULES` приводит к ImportError при импорте этого
    модуля — это сигнал что разработчик забыл вписать новый код выше.
    """
    if module_code not in KNOWN_MODULES:
        raise ImportError(
            f"feature_flags: unknown module {module_code!r} — "
            f"add it to KNOWN_MODULES in services/feature_flags.py"
        )

    async def _checker(
        user: CurrentUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_db),
    ) -> CurrentUser:
        if module_code in ALWAYS_ENABLED:
            return user
        enabled = await is_module_enabled(session, user.tenant_id, module_code)
        if not enabled:
            raise HTTPException(
                403,
                {
                    "error": "module_disabled",
                    "module": module_code,
                    "message": (
                        f"Модуль «{module_code}» не подключён для вашего "
                        f"тарифа. Обратитесь к администратору сервиса."
                    ),
                },
            )
        return user

    return _checker
