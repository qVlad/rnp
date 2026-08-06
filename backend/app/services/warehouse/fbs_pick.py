"""Отбор по FBS-заказам WB (TASK-DEV-098, Фаза 3).

Поток, запускаемый кнопкой «Собрать отбор» (фонового опроса WB нет — решение
пользователя):

  1. по каждому связанному кабинету его собственным токеном дёргаем
     `GET /api/v3/orders/new` И `GET /api/v3/orders` за последние N дней —
     второе обязательно, потому что задание, попавшее в поставку, становится
     `confirm` и из `/orders/new` исчезает, хотя товар ещё не собран;
  2. оставляем только задания на наш физический склад — по `warehouseId` из
     `wh_warehouse_wb_link` (у одного склада свой ID в каждом кабинете);
  3. группируем по кабинету и баркоду: qty = число заданий (одно задание =
     одна единица товара);
  4. резолвим, откуда брать: сначала ячейки отбора по маршруту, затем коробы
     на хранении; нехватка → `shortage` в строке;
  5. создаём **отдельный лист отбора на каждый кабинет**.

`skus[0]` в задании — это баркод, ровно та же строка, что `WhBoxItem.barcode`,
поэтому матч прямой и `nm_id` для отбора не нужен.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wb import marketplace
from app.integrations.wb.client import WbApiClient
from app.db.models import (
    Tenant,
    WhBox,
    WhBoxItem,
    WhCell,
    WhFbsOrder,
    WhMovement,
    WhPickLine,
    WhPickOrder,
    WhWarehouseWbLink,
)
from app.services.box_distribution import normalize_barcode
from app.services.tenant_context import get_tenant
from app.sync.tenants import get_tenant_token


def _parse_wb_dt(raw: Any) -> datetime | None:
    """`2022-05-04T07:56:29Z` → aware datetime."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


async def cabinet_links(
    session: AsyncSession, warehouse_id: int
) -> list[WhWarehouseWbLink]:
    """Активные связки склада с кабинетами WB."""
    return list(
        (
            await session.execute(
                select(WhWarehouseWbLink)
                .where(WhWarehouseWbLink.warehouse_id == warehouse_id)
                .where(WhWarehouseWbLink.is_active.is_(True))
                .order_by(WhWarehouseWbLink.cabinet_tenant_id)
            )
        )
        .scalars()
        .all()
    )


# Сколько дней истории заданий тянем по умолчанию. WB разрешает ≤30 дней за
# запрос и хранит задания 3 месяца.
DEFAULT_DAYS_BACK = 7
MAX_DAYS_BACK = 30

# Статусы, при которых товар ещё нужно физически отобрать: `new` (не в поставке)
# и `confirm` (уже в поставке — в т.ч. созданной в ЛК WB руками, но не собранной).
PICKABLE_STATUSES = ("new", "confirm")


async def fetch_fbs_orders(
    session: AsyncSession,
    warehouse_id: int,
    cabinet_tenant_ids: list[int] | None = None,
    days_back: int = DEFAULT_DAYS_BACK,
) -> dict[str, Any]:
    """Забрать сборочные задания, которые ещё нужно отобрать.

    Берём НЕ только `/orders/new`: как только задание попадает в поставку, оно
    становится `confirm` и из `/orders/new` исчезает, хотя товар не собран.
    Найдено на проде: в кабинете 0 «новых» и 10 «на сборке» — отбор строился
    пустым. Поэтому тянем `/api/v3/orders` за период + статусы батчем и
    оставляем `new` + `confirm`.

    Кабинеты обходим последовательно: лимит WB (300/мин) — **на аккаунт
    продавца**, поэтому бюджеты кабинетов независимы, но открывать 5 клиентов
    параллельно смысла нет, а ошибку одного кабинета не должна ронять весь
    отбор — она попадает в `errors`.
    """
    links = await cabinet_links(session, warehouse_id)
    if cabinet_tenant_ids:
        wanted = set(cabinet_tenant_ids)
        links = [x for x in links if x.cabinet_tenant_id in wanted]
    if not links:
        return {"fetched": 0, "cabinets": [], "errors": ["no_wb_links"]}

    # У одного кабинета может быть несколько WB-складов на этот физический
    # склад — собираем множество допустимых warehouseId.
    wh_ids_by_cabinet: dict[int, set[int]] = {}
    for link in links:
        wh_ids_by_cabinet.setdefault(link.cabinet_tenant_id, set()).add(
            int(link.wb_warehouse_id)
        )

    tenant_id = get_tenant(session)
    now = datetime.now(timezone.utc)
    cabinets: list[dict[str, Any]] = []
    errors: list[str] = []
    total_fetched = 0

    for cabinet_tenant_id, allowed_wh in wh_ids_by_cabinet.items():
        cabinet = await session.get(Tenant, cabinet_tenant_id)
        cabinet_name = cabinet.name if cabinet else str(cabinet_tenant_id)
        token = await get_tenant_token(session, cabinet_tenant_id)
        if not token:
            errors.append(f"{cabinet_name}: нет WB-токена")
            continue
        window = max(1, min(int(days_back or DEFAULT_DAYS_BACK), MAX_DAYS_BACK))
        try:
            async with WbApiClient(token=token) as client:
                # `/orders/new` — быстрый путь; `/api/v3/orders` добирает то, что
                # уже в поставках. Мёржим по id, статусы запрашиваем один раз.
                fresh = await marketplace.get_new_orders(client)
                ts_to = int(datetime.now(timezone.utc).timestamp())
                ts_from = ts_to - window * 86400
                history = await marketplace.get_orders(client, ts_from, ts_to)
                by_id: dict[int, dict[str, Any]] = {}
                for o in [*history, *fresh]:  # fresh последним — он приоритетнее
                    oid = int(o.get("id") or 0)
                    if oid:
                        by_id[oid] = o
                statuses: dict[int, dict[str, Any]] = {}
                if by_id:
                    for row in await marketplace.get_orders_status(
                        client, list(by_id)
                    ):
                        rid = int(row.get("id") or 0)
                        if rid:
                            statuses[rid] = row
                # `/orders/new` статуса не содержит, но он по определению `new`
                for o in fresh:
                    oid = int(o.get("id") or 0)
                    statuses.setdefault(oid, {"supplierStatus": "new"})
                orders = list(by_id.values())
        except Exception as exc:  # noqa: BLE001 — один кабинет не валит остальные
            errors.append(f"{cabinet_name}: {exc}")
            continue

        matched = 0
        skipped_other_wh = 0
        skipped_status: dict[str, int] = {}
        for order in orders:
            status_row = statuses.get(int(order.get("id") or 0), {})
            supplier_status = str(status_row.get("supplierStatus") or "new")
            if supplier_status not in PICKABLE_STATUSES:
                # complete / cancel — собирать нечего
                skipped_status[supplier_status] = (
                    skipped_status.get(supplier_status, 0) + 1
                )
                continue
            wb_wh = order.get("warehouseId")
            if wb_wh is not None and int(wb_wh) not in allowed_wh:
                skipped_other_wh += 1
                continue
            skus = order.get("skus") or []
            barcode = normalize_barcode(skus[0] if skus else None)
            if not barcode:
                continue
            wb_order_id = int(order.get("id") or 0)
            if not wb_order_id:
                continue

            existing = (
                await session.execute(
                    select(WhFbsOrder)
                    .where(WhFbsOrder.cabinet_tenant_id == cabinet_tenant_id)
                    .where(WhFbsOrder.wb_order_id == wb_order_id)
                )
            ).scalars().first()
            offices = order.get("offices") or []
            values = {
                "rid": order.get("rid"),
                "barcode": barcode,
                "nm_id": order.get("nmId"),
                "chrt_id": order.get("chrtId"),
                "article": order.get("article"),
                "wb_warehouse_id": wb_wh,
                "office_id": order.get("officeId"),
                "office_name": offices[0] if offices else None,
                "price_kop": order.get("salePrice") or order.get("finalPrice"),
                "cargo_type": order.get("cargoType"),
                "required_meta": {
                    "required": order.get("requiredMeta") or [],
                    "optional": order.get("optionalMeta") or [],
                },
                "wb_created_at": _parse_wb_dt(order.get("createdAt")),
                "supply_wb_id": order.get("supplyId") or None,
                "supplier_status": supplier_status,
                "wb_status": status_row.get("wbStatus"),
                "fetched_at": now,
            }
            if existing is None:
                session.add(
                    WhFbsOrder(
                        tenant_id=tenant_id,
                        cabinet_tenant_id=cabinet_tenant_id,
                        wb_order_id=wb_order_id,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            matched += 1

        total_fetched += matched
        cabinets.append(
            {
                "cabinet_tenant_id": cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "orders_total": len(orders),
                "orders_for_warehouse": matched,
                "skipped_other_warehouse": skipped_other_wh,
                "skipped_by_status": skipped_status,
                "days_back": window,
            }
        )

    await session.flush()
    return {"fetched": total_fetched, "cabinets": cabinets, "errors": errors}


async def _available_sources(
    session: AsyncSession, warehouse_id: int, barcodes: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Откуда можно взять каждый баркод: сначала ячейки отбора, потом хранение.

    Возвращает `{barcode: [{box_id, box_code, cell_id, cell_code, sort_order,
    qty}]}` в порядке, в котором нужно брать.
    """
    if not barcodes:
        return {}
    rows = (
        await session.execute(
            select(
                WhBoxItem.barcode,
                WhBoxItem.qty,
                WhBox.id.label("box_id"),
                WhBox.box_code,
                WhBox.status,
                WhCell.id.label("cell_id"),
                WhCell.code.label("cell_code"),
                WhCell.sort_order,
            )
            .join(WhBox, WhBox.id == WhBoxItem.box_id)
            .outerjoin(WhCell, WhCell.id == WhBox.cell_id)
            .where(WhBox.warehouse_id == warehouse_id)
            .where(WhBox.status.in_(("pick", "received", "storage")))
            .where(WhBoxItem.qty > 0)
            .where(WhBoxItem.barcode.in_(list(barcodes)))
        )
    ).all()

    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.barcode, []).append(
            {
                "box_id": r.box_id,
                "box_code": r.box_code,
                "cell_id": r.cell_id,
                "cell_code": r.cell_code,
                "sort_order": int(r.sort_order or 0),
                "qty": int(r.qty or 0),
                "in_pick_zone": r.status == "pick" and r.cell_id is not None,
            }
        )
    for lst in out.values():
        # Сначала зона отбора (по маршруту), потом хранение — кладовщик не
        # должен лезть в запас, если товар доступен на пик-фейсе.
        lst.sort(
            key=lambda s: (
                0 if s["in_pick_zone"] else 1,
                s["sort_order"],
                s["box_code"],
            )
        )
    return out


async def build_pick_orders(
    session: AsyncSession,
    warehouse_id: int,
    *,
    cabinet_tenant_ids: list[int] | None = None,
    actor: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Собрать листы отбора из уже загруженных заданий FBS.

    Один лист на кабинет. Резервирование мягкое: строки указывают, откуда
    брать, но `qty` в коробе уменьшается только при фактическом отборе
    (`pick_line`) — иначе незакрытый лист «съедал» бы остаток.
    """
    tenant_id = get_tenant(session)
    stmt = (
        select(WhFbsOrder)
        .where(WhFbsOrder.supplier_status.in_(PICKABLE_STATUSES))
        .where(WhFbsOrder.pick_order_id.is_(None))
    )
    if cabinet_tenant_ids:
        stmt = stmt.where(WhFbsOrder.cabinet_tenant_id.in_(cabinet_tenant_ids))
    orders = list((await session.execute(stmt)).scalars().all())
    if not orders:
        return {"pick_orders": [], "stats": {"orders": 0, "cabinets": 0}}

    # Задание = 1 шт, поэтому qty по баркоду = число заданий.
    by_cabinet: dict[int, dict[str, list[WhFbsOrder]]] = {}
    for o in orders:
        by_cabinet.setdefault(o.cabinet_tenant_id, {}).setdefault(o.barcode, []).append(o)

    all_barcodes = {o.barcode for o in orders}
    sources = await _available_sources(session, warehouse_id, all_barcodes)
    # Сколько уже «расписано» по строкам этого прогона — чтобы два кабинета не
    # претендовали на один и тот же остаток.
    consumed: dict[tuple[str, int], int] = {}

    now = datetime.now(timezone.utc)
    result: list[dict[str, Any]] = []

    for cabinet_tenant_id, per_barcode in sorted(by_cabinet.items()):
        cabinet = await session.get(Tenant, cabinet_tenant_id)
        cabinet_name = cabinet.name if cabinet else str(cabinet_tenant_id)

        pick_order: WhPickOrder | None = None
        if not dry_run:
            pick_order = WhPickOrder(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                cabinet_tenant_id=cabinet_tenant_id,
                name=f"Отбор {cabinet_name} {now:%d.%m %H:%M}",
                status="draft",
                actor=actor,
                created_at=now,
            )
            session.add(pick_order)
            await session.flush()

        lines: list[dict[str, Any]] = []
        for barcode, fbs_orders in per_barcode.items():
            need = len(fbs_orders)
            for src in sources.get(barcode, []):
                if need <= 0:
                    break
                key = (barcode, src["box_id"])
                left = src["qty"] - consumed.get(key, 0)
                if left <= 0:
                    continue
                take = min(need, left)
                consumed[key] = consumed.get(key, 0) + take
                need -= take
                line = {
                    "barcode": barcode,
                    "cell_id": src["cell_id"],
                    "cell_code": src["cell_code"],
                    "box_id": src["box_id"],
                    "box_code": src["box_code"],
                    "qty_required": take,
                    "shortage": 0,
                    "sort_order": src["sort_order"],
                }
                lines.append(line)
                if pick_order is not None:
                    session.add(
                        WhPickLine(
                            tenant_id=tenant_id,
                            pick_order_id=pick_order.id,
                            barcode=barcode,
                            cell_id=src["cell_id"],
                            box_id=src["box_id"],
                            qty_required=take,
                            sort_order=src["sort_order"],
                        )
                    )
            if need > 0:
                # Недостача: заданий больше, чем товара на складе. Строку всё
                # равно создаём — кладовщик должен видеть, чего не хватает.
                lines.append(
                    {
                        "barcode": barcode,
                        "cell_id": None,
                        "cell_code": None,
                        "box_id": None,
                        "box_code": None,
                        "qty_required": need,
                        "shortage": need,
                        # недостачу показываем в конце маршрута
                        "sort_order": 10**9,
                    }
                )
                if pick_order is not None:
                    session.add(
                        WhPickLine(
                            tenant_id=tenant_id,
                            pick_order_id=pick_order.id,
                            barcode=barcode,
                            qty_required=need,
                            shortage=need,
                            sort_order=10**9,
                        )
                    )

        cabinet_orders = [x for lst in per_barcode.values() for x in lst]
        # Если задания уже лежат в поставке WB (созданной в ЛК), новую создавать
        # нельзя — подхватываем существующую, чтобы кнопка «Поставка» не плодила
        # дубли, а сразу предлагала «В доставку».
        existing_supplies = {o.supply_wb_id for o in cabinet_orders if o.supply_wb_id}
        if pick_order is not None:
            if len(existing_supplies) == 1:
                pick_order.wb_supply_id = next(iter(existing_supplies))
                pick_order.status = "in_progress"
            for o in cabinet_orders:
                o.pick_order_id = pick_order.id

        lines.sort(key=lambda x: (x["sort_order"], x["barcode"]))
        result.append(
            {
                "pick_order_id": pick_order.id if pick_order else None,
                "cabinet_tenant_id": cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "name": pick_order.name if pick_order else f"Отбор {cabinet_name}",
                "orders": sum(len(v) for v in per_barcode.values()),
                "wb_supply_id": (
                    next(iter(existing_supplies)) if len(existing_supplies) == 1 else None
                ),
                "wb_supplies": sorted(x for x in existing_supplies if x),
                "lines": lines,
                "qty_required": sum(x["qty_required"] for x in lines),
                "shortage": sum(x["shortage"] for x in lines),
            }
        )

    if not dry_run:
        await session.flush()
    return {
        "pick_orders": result,
        "stats": {
            "orders": len(orders),
            "cabinets": len(result),
            "qty_required": sum(p["qty_required"] for p in result),
            "shortage": sum(p["shortage"] for p in result),
        },
    }


async def pick_line(
    session: AsyncSession,
    line_id: int,
    qty: int,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Отметить фактический отбор по строке: списать товар из короба.

    Списываем ровно из того короба, который указан в строке. Короб, из которого
    забрали всё, помечаем `empty` и освобождаем ячейку — иначе адрес останется
    занятым пустой тарой.
    """
    line = await session.get(WhPickLine, line_id)
    if line is None:
        raise ValueError("pick_line_not_found")
    pick_order = await session.get(WhPickOrder, line.pick_order_id)
    if pick_order is None:
        raise ValueError("pick_order_not_found")

    take = max(0, int(qty))
    remaining_need = max(0, int(line.qty_required) - int(line.qty_picked))
    take = min(take, remaining_need)
    if take == 0:
        return {"picked": 0, "line_id": line_id, "qty_picked": int(line.qty_picked)}
    if line.box_id is None:
        raise ValueError("line_has_no_source")

    item = (
        await session.execute(
            select(WhBoxItem)
            .where(WhBoxItem.box_id == line.box_id)
            .where(WhBoxItem.barcode == line.barcode)
        )
    ).scalars().first()
    if item is None or int(item.qty or 0) <= 0:
        raise ValueError("nothing_left_in_box")
    take = min(take, int(item.qty))

    item.qty = int(item.qty) - take
    line.qty_picked = int(line.qty_picked) + take

    box = await session.get(WhBox, line.box_id)
    cell_from = box.cell_id if box else None
    session.add(
        WhMovement(
            tenant_id=get_tenant(session),
            warehouse_id=pick_order.warehouse_id,
            dt=datetime.now(timezone.utc),
            kind="pick",
            box_id=line.box_id,
            barcode=line.barcode,
            qty=take,
            cell_from_id=cell_from,
            doc_ref=pick_order.name,
            actor=actor,
        )
    )

    # Короб опустел — освобождаем ячейку
    box_emptied = False
    if box is not None:
        left = int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(WhBoxItem.qty), 0)).where(
                        WhBoxItem.box_id == box.id
                    )
                )
            ).scalar()
            or 0
        )
        if left == 0:
            box.status = "empty"
            box.cell_id = None
            box_emptied = True

    if pick_order.status == "draft":
        pick_order.status = "in_progress"

    return {
        "picked": take,
        "line_id": line_id,
        "qty_picked": int(line.qty_picked),
        "qty_required": int(line.qty_required),
        "box_emptied": box_emptied,
        "cell_freed": cell_from if box_emptied else None,
    }
