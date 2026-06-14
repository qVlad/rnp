"""Синхронизация склеек WB (TASK-DEV-082, TS-parity «Синхронизация склеек»).

WB объединяет карточки одного товара (разные цвета/комплектации) в «склейку» —
у всех общий `imtID` (Content API). TrueStats авто-группирует их кнопкой
«Синхронизация склеек». Здесь то же:

1. Тянем карточки (`/content/v2/get/cards/list`) → nm→imtID.
2. Обновляем `products.imt_id`.
3. Для каждого imtID, под которым ≥2 наших nm_id, создаём/обновляем
   ProductGroup `Склейка: <imtID>` и синхронизируем членов (assignments).

Идемпотентно: управляем ТОЛЬКО группами с префиксом `Склейка: ` (ручные группы
не трогаем). Повторный запуск приводит членство к актуальному состоянию WB.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Product, ProductGroup, ProductGroupAssignment
from app.integrations.wb.content import fetch_cards_list
from app.integrations.wb.client import WbApiClient

log = get_logger(__name__)

SKLEIKA_PREFIX = "Склейка: "


async def sync_skleika(
    session: AsyncSession, *, tenant_id: int, token: str
) -> dict[str, Any]:
    """Тянет imtID из WB Content API, обновляет products.imt_id и
    авто-группирует склейки. Возвращает сводку."""
    # 1) nm → imtID из WB.
    nm_to_imt: dict[int, int] = {}
    async with WbApiClient(token=token) as client:
        async for page in fetch_cards_list(client, limit=100):
            for card in page:
                nm = card.get("nmID")
                imt = card.get("imtID")
                if isinstance(nm, int) and isinstance(imt, int):
                    nm_to_imt[int(nm)] = int(imt)

    if not nm_to_imt:
        return {"status": "ok", "cards": 0, "skleikas": 0, "tagged": 0,
                "note": "WB не вернул карточек с imtID"}

    # 2) Обновляем products.imt_id только для наших (tenant) nm.
    our_nms = set(
        (
            await session.execute(
                select(Product.nm_id).where(
                    Product.tenant_id == tenant_id,
                    Product.nm_id.in_(list(nm_to_imt.keys())),
                )
            )
        ).scalars().all()
    )
    tagged = 0
    for nm in our_nms:
        imt = nm_to_imt.get(int(nm))
        if imt is not None:
            await session.execute(
                Product.__table__.update()
                .where(Product.tenant_id == tenant_id, Product.nm_id == nm)
                .values(imt_id=imt)
            )
            tagged += 1

    # 3) Группируем наши nm по imtID (только склейки с ≥2 nm).
    imt_to_nms: dict[int, list[int]] = {}
    for nm in our_nms:
        imt = nm_to_imt.get(int(nm))
        if imt is None:
            continue
        imt_to_nms.setdefault(imt, []).append(int(nm))
    multi = {imt: nms for imt, nms in imt_to_nms.items() if len(nms) >= 2}

    groups_created = 0
    groups_updated = 0
    for imt, nms in multi.items():
        name = f"{SKLEIKA_PREFIX}{imt}"
        grp = (
            await session.execute(
                select(ProductGroup).where(
                    ProductGroup.tenant_id == tenant_id, ProductGroup.name == name
                )
            )
        ).scalars().first()
        if grp is None:
            grp = ProductGroup(
                tenant_id=tenant_id, name=name,
                comment="Авто-склейка WB (imtID). Обновляется кнопкой «Синхронизация склеек».",
            )
            session.add(grp)
            await session.flush()
            groups_created += 1
        else:
            groups_updated += 1
        # Синхронизируем членов: удаляем старых, ставим актуальных.
        await session.execute(
            delete(ProductGroupAssignment).where(
                ProductGroupAssignment.tenant_id == tenant_id,
                ProductGroupAssignment.group_id == grp.id,
            )
        )
        for nm in nms:
            session.add(
                ProductGroupAssignment(tenant_id=tenant_id, group_id=grp.id, nm_id=nm)
            )

    await session.commit()
    return {
        "status": "ok",
        "cards": len(nm_to_imt),
        "tagged": tagged,
        "skleikas": len(multi),
        "groups_created": groups_created,
        "groups_updated": groups_updated,
    }
