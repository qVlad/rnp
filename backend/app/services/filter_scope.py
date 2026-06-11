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
    """DEV-062 Phase C: валидировать выбранные магазины (кабинеты) против
    `user_tenant_access`.

    Возврат: `list[int]` из ≥2 разрешённых tenant'ов (режим «свод по магазинам»)
    или `None` (0/1 магазин ИЛИ нет доступа → обычный single-tenant активный
    кабинет). Защита: показываем только tenant'ы, к которым у user есть доступ.

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
    ids = [int(x) for x in _csv(stores) if x.lstrip("-").isdigit()]
    if len(ids) < 2:
        return None  # 0/1 магазин → обычный активный кабинет (без расширения)
    acc = (
        await session.execute(
            text("select tenant_id from user_tenant_access where user_id = :u"),
            {"u": user_id},
        )
    ).all()
    allowed = {int(r[0]) for r in acc} or {int(fallback_tenant_id)}
    validated = [t for t in ids if t in allowed]
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
