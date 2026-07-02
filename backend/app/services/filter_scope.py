"""Глобальные фильтры (TASK-DEV-062) — резолвер выбранных измерений в набор nm_id.

Единый источник истины для фильтрации аналитики по комбинации:
бренды × категории × группы × артикулы (как в TrueStats). Магазины (мульти-кабинет)
— отдельная фаза (кросс-tenant), здесь не обрабатываются.

`resolve_nm_scope(...)` возвращает `set[int]` (разрешённые nm_id) или `None`
(без ограничений). Пересекает все ЗАДАННЫЕ измерения, затем пересекает с RBAC
(manager brand-scope). Пустой набор — валиден (показать пусто).
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductGroupAssignment


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


async def resolve_store_scope(
    session: AsyncSession,
    *,
    stores: str | None,
    user_id: int,
    fallback_tenant_id: int,
    rbac_brands: set[str] | None = "__unset__",  # type: ignore[assignment]
) -> list[int] | None:
    """DEV-062 Phase C / DEV-092: свод по кабинетам.

    Возврат:
      * `stores` НЕ передан → все видимые (не hidden) кабинеты user'а, если их
        ≥2 — **свод по умолчанию** (как TrueStats); один кабинет → None
        (обычный single-tenant режим).
      * `stores` передан → validated-список выбранных (включая ровно один —
        явное сужение до конкретного магазина); мусор/чужие id отбрасываются,
        если ничего валидного не осталось → None.
    Защита: только tenant'ы из `user_tenant_access`, скрытые (hidden_at)
    исключаются. `None` = caller оставляет обычный активный кабинет.

    **BUG-DEV-023:** brand-scoped роль (manager, `rbac_brands` — непустой set ИЛИ
    пустой) НЕ допускается к кросс-tenant своду: RBAC задан по brand-name в
    рамках одного кабинета и при расширении на другой tenant утёк бы на
    одноимённые бренды. Мульти-магазин — только для unrestricted ролей
    (director/head, `rbac_brands is None`). `"__unset__"` — back-compat для
    вызовов без передачи RBAC (трактуем как «не ограничивать», но такие вызовы
    надо обновить).
    """
    if rbac_brands is not None and rbac_brands != "__unset__":
        return None  # manager (brand-scope) — без кросс-tenant свода
    acc = (
        await session.execute(
            text(
                "select a.tenant_id from user_tenant_access a "
                "join tenants t on t.id = a.tenant_id "
                "where a.user_id = :u and t.hidden_at is null"
            ),
            {"u": user_id},
        )
    ).all()
    allowed = {int(r[0]) for r in acc} or {int(fallback_tenant_id)}
    ids = [int(x) for x in _csv(stores) if x.lstrip("-").isdigit()]
    if not ids:
        # DEV-092: свод ПО УМОЛЧАНИЮ (как TrueStats) — без выбранных магазинов
        # director/head видит сумму по ВСЕМ своим видимым кабинетам.
        # Один кабинет → обычный single-tenant режим (None).
        all_ids = sorted(allowed)
        return all_ids if len(all_ids) >= 2 else None
    validated = [t for t in ids if t in allowed]
    if len(validated) == 1:
        return validated  # выбран один магазин — явное сужение до него
    return validated if len(validated) >= 2 else None


async def resolve_nm_scope(
    session: AsyncSession,
    *,
    brands: str | None = None,
    categories: str | None = None,
    groups: str | None = None,
    articles: str | None = None,
    rbac_brands: set[str] | None = None,
) -> set[int] | None:
    """Свести выбор фильтров к набору nm_id.

    Параметры (CSV-строки из query): brands, categories (по products.category),
    groups (id групп), articles (nm_id). rbac_brands — ограничение роли
    (manager): None = без ограничений.

    Возврат: None — фильтров нет и роль без ограничений (весь скоуп);
    иначе set[int] разрешённых nm_id (возможно пустой).
    """
    dims: list[set[int]] = []

    br = _csv(brands)
    cat = _csv(categories)
    grp = [int(x) for x in _csv(groups) if x.isdigit()]
    art = [int(x) for x in _csv(articles) if x.lstrip("-").isdigit()]

    if br:
        rows = (await session.execute(
            select(Product.nm_id).where(Product.brand.in_(br))
        )).scalars().all()
        dims.append({int(n) for n in rows if n is not None})

    if cat:
        rows = (await session.execute(
            select(Product.nm_id).where(Product.category.in_(cat))
        )).scalars().all()
        dims.append({int(n) for n in rows if n is not None})

    if grp:
        rows = (await session.execute(
            select(ProductGroupAssignment.nm_id).where(ProductGroupAssignment.group_id.in_(grp))
        )).scalars().all()
        dims.append({int(n) for n in rows if n is not None})

    if art:
        dims.append({int(n) for n in art})

    # RBAC manager-scope → набор nm_id по разрешённым брендам.
    if rbac_brands is not None:
        rows = (await session.execute(
            select(Product.nm_id).where(Product.brand.in_(rbac_brands))
        )).scalars().all()
        dims.append({int(n) for n in rows if n is not None})

    if not dims:
        return None  # фильтров нет, роль без ограничений

    scope = dims[0]
    for d in dims[1:]:
        scope &= d
    return scope
