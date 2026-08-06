"""Остатки FBS в WB: сверка и запись по кнопке (TASK-DEV-098, Фаза 4).

Наш склад может быть источником истины для FBS-доступности — тогда WB не
продаёт то, чего физически нет. Но **автопуша нет by design**: ошибка в
приёмке или неполный разбор поставки мгновенно и молча обнулили бы витрину WB.
Поэтому сначала `preview` («в WB / у нас / Δ»), потом явный `push`.

Что считается «нашим остатком»: сумма `WhBoxItem.qty` по складу для коробов в
статусах наличия (`received` / `pick` / `storage`). Пустые и отгруженные коробы
не участвуют.

Сколько отправлять — три режима (запрос пользователя 2026-08-06):
  - `all`     — весь фактический остаток;
  - `fixed`   — по N штук на баркод (если на складе меньше — сколько есть);
  - `percent` — P% от остатка баркода.

**Единица — баркод (размер), а не артикул** (решение пользователя): в WB остаток
ведётся именно так, и каждый размер остаётся в продаже. «10 шт на артикул» из 9
размеров = 90 шт всего.

Лимиты (`specs/02-items.yaml`): `POST /api/v3/stocks/{warehouseId}` — читать,
`PUT` — писать, оба по 1000 sku за запрос, 300 запросов/мин на кабинет.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant, WhBox, WhBoxItem, WhWarehouseWbLink
from app.integrations.wb import marketplace
from app.integrations.wb.client import WbApiClient
from app.services.warehouse.fbs_stock_policy import PUSH_MODES, compute_target  # noqa: F401
from app.services.warehouse.stock import IN_STOCK_STATUSES
from app.sync.tenants import get_tenant_token


async def our_stock(session: AsyncSession, warehouse_id: int) -> dict[str, int]:
    """`{barcode: qty}` — наши остатки по складу."""
    rows = (
        await session.execute(
            select(WhBoxItem.barcode, func.coalesce(func.sum(WhBoxItem.qty), 0))
            .join(WhBox, WhBox.id == WhBoxItem.box_id)
            .where(WhBox.warehouse_id == warehouse_id)
            .where(WhBox.status.in_(IN_STOCK_STATUSES))
            .group_by(WhBoxItem.barcode)
        )
    ).all()
    return {r[0]: int(r[1] or 0) for r in rows if r[0]}


async def _links(
    session: AsyncSession, warehouse_id: int, cabinet_tenant_ids: list[int] | None
) -> list[WhWarehouseWbLink]:
    stmt = (
        select(WhWarehouseWbLink)
        .where(WhWarehouseWbLink.warehouse_id == warehouse_id)
        .where(WhWarehouseWbLink.is_active.is_(True))
        .order_by(WhWarehouseWbLink.cabinet_tenant_id)
    )
    if cabinet_tenant_ids:
        stmt = stmt.where(WhWarehouseWbLink.cabinet_tenant_id.in_(cabinet_tenant_ids))
    return list((await session.execute(stmt)).scalars().all())


async def preview(
    session: AsyncSession,
    warehouse_id: int,
    cabinet_tenant_ids: list[int] | None = None,
    mode: str = "all",
    value: int = 0,
) -> dict[str, Any]:
    """Сверка «в WB / у нас на складе / отправим» по каждому кабинету.

    Ничего не пишет. В `diff` попадают только расхождения между тем, что в WB, и
    тем, что отправим по выбранному режиму — совпадающие позиции трогать незачем.
    """
    ours = await our_stock(session, warehouse_id)
    target = compute_target(ours, mode, value)
    links = await _links(session, warehouse_id, cabinet_tenant_ids)
    if not links:
        return {
            "cabinets": [],
            "our_barcodes": len(ours),
            "mode": mode,
            "value": value,
            "errors": ["no_wb_links"],
        }

    cabinets: list[dict[str, Any]] = []
    errors: list[str] = []
    barcodes = list(ours.keys())

    for link in links:
        cabinet = await session.get(Tenant, link.cabinet_tenant_id)
        cabinet_name = cabinet.name if cabinet else str(link.cabinet_tenant_id)
        token = await get_tenant_token(session, link.cabinet_tenant_id)
        if not token:
            errors.append(f"{cabinet_name}: нет WB-токена")
            continue
        try:
            async with WbApiClient(token=token) as client:
                in_wb = await marketplace.get_fbs_stocks(
                    client, link.wb_warehouse_id, barcodes
                )
        except Exception as exc:  # noqa: BLE001 — один кабинет не валит остальные
            errors.append(f"{cabinet_name}: {exc}")
            continue

        diff = []
        for barcode in barcodes:
            wb_qty = int(in_wb.get(barcode, 0))
            our_qty = int(ours.get(barcode, 0))
            send_qty = int(target.get(barcode, 0))
            if wb_qty != send_qty:
                diff.append(
                    {
                        "barcode": barcode,
                        "in_wb": wb_qty,
                        # фактический остаток склада — чтобы видеть, из чего считали
                        "ours": our_qty,
                        # сколько отправим по выбранному режиму
                        "target": send_qty,
                        "delta": send_qty - wb_qty,
                    }
                )
        diff.sort(key=lambda d: (-abs(d["delta"]), d["barcode"]))
        cabinets.append(
            {
                "cabinet_tenant_id": link.cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "wb_warehouse_id": link.wb_warehouse_id,
                "wb_warehouse_name": link.wb_warehouse_name,
                "checked": len(barcodes),
                "matching": len(barcodes) - len(diff),
                "diff_count": len(diff),
                "diff": diff[:500],
                "diff_truncated": len(diff) > 500,
            }
        )

    return {
        "cabinets": cabinets,
        "our_barcodes": len(ours),
        "our_total_qty": sum(ours.values()),
        "mode": mode,
        "value": value,
        # сколько всего штук уйдёт по выбранному режиму (на один кабинет)
        "target_total_qty": sum(target.values()),
        "errors": errors,
    }


async def push(
    session: AsyncSession,
    warehouse_id: int,
    cabinet_tenant_ids: list[int] | None = None,
    barcodes: list[str] | None = None,
    mode: str = "all",
    value: int = 0,
) -> dict[str, Any]:
    """Записать остатки в WB (`PUT /api/v3/stocks/{warehouseId}`).

    Отправляем ТОЛЬКО расходящиеся позиции (или явно выбранные `barcodes`) — так
    и запросов меньше, и в audit_log видно, что именно поменяли. Сколько именно
    отправлять, решает `mode`/`value` (см. `compute_target`).
    """
    ours = await our_stock(session, warehouse_id)
    target = compute_target(ours, mode, value)
    links = await _links(session, warehouse_id, cabinet_tenant_ids)
    if not links:
        return {
            "cabinets": [],
            "summary": {"cabinets": 0, "positions": 0, "mode": mode, "value": value},
            "errors": ["no_wb_links"],
        }

    wanted = {str(b) for b in barcodes if b} if barcodes else None
    cabinets: list[dict[str, Any]] = []
    errors: list[str] = []
    total_positions = 0

    for link in links:
        cabinet = await session.get(Tenant, link.cabinet_tenant_id)
        cabinet_name = cabinet.name if cabinet else str(link.cabinet_tenant_id)
        token = await get_tenant_token(session, link.cabinet_tenant_id)
        if not token:
            errors.append(f"{cabinet_name}: нет WB-токена")
            continue
        try:
            async with WbApiClient(token=token) as client:
                # Читаем текущее состояние, чтобы не отправлять совпадающее.
                in_wb = await marketplace.get_fbs_stocks(
                    client, link.wb_warehouse_id, list(ours.keys())
                )
                to_push = {
                    barcode: qty
                    for barcode, qty in target.items()
                    if (wanted is None or barcode in wanted)
                    and int(in_wb.get(barcode, 0)) != int(qty)
                }
                sent = 0
                if to_push:
                    sent = await marketplace.put_fbs_stocks(
                        client, link.wb_warehouse_id, to_push
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cabinet_name}: {exc}")
            continue

        total_positions += sent
        cabinets.append(
            {
                "cabinet_tenant_id": link.cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "wb_warehouse_id": link.wb_warehouse_id,
                "pushed": sent,
                "examples": [
                    {"barcode": b, "qty": q} for b, q in list(to_push.items())[:20]
                ],
            }
        )

    return {
        "cabinets": cabinets,
        "summary": {
            "cabinets": len(cabinets),
            "positions": total_positions,
            "our_barcodes": len(ours),
            "mode": mode,
            "value": value,
            "target_total_qty": sum(target.values()),
        },
        "errors": errors,
    }
