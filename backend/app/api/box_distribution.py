"""Box Distribution — мобильный QR-сканер раскладки коробов (DEV-091).

Workflow: загрузка файла «Распределение» → скан QR (ШК короба ALT-...) →
подсказка раскладки по складам в WB-короба (WB_1541505000++, накопительно) →
ручная правка количеств → «Заполнено»/«Распределено» → экспорт shk-excel.

См. UNIT-план/promo_calculator для паттернов upload/xlsx.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    BoxDistributionSrc,
    BoxDistributionWbBox,
    BoxDistributionWbItem,
)
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.box_distribution import (
    WAREHOUSE_ALIASES_SEED,
    build_shk_xlsx,
    normalize_warehouse,
    parse_distribution_file,
)

router = APIRouter(
    prefix="/api/box-distribution",
    tags=["box-distribution"],
    dependencies=[Depends(require_director_or_head)],
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_KEY_NEXT_WB = "box_distribution.next_wb"
_KEY_ALIASES = "box_distribution.wh_aliases"
_DEFAULT_START_WB = 1541505000


# ── AppSetting helpers (tenant-scoped, pitfall #16) ──────────────────────────


async def _get_setting(session: AsyncSession, tenant_id: int, key: str) -> str | None:
    row = (
        await session.execute(
            select(AppSetting.value).where(
                AppSetting.tenant_id == tenant_id, AppSetting.key == key
            )
        )
    ).scalar_one_or_none()
    return row


async def _set_setting(
    session: AsyncSession, tenant_id: int, key: str, value: str
) -> None:
    stmt = pg_insert(AppSetting).values(tenant_id=tenant_id, key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "key"], set_={"value": value}
    )
    await session.execute(stmt)


async def _get_aliases(session: AsyncSession, tenant_id: int) -> dict[str, str]:
    raw = await _get_setting(session, tenant_id, _KEY_ALIASES)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


async def _get_start_wb(session: AsyncSession, tenant_id: int) -> int:
    raw = await _get_setting(session, tenant_id, "box_distribution.start_wb")
    try:
        return int(raw) if raw else _DEFAULT_START_WB
    except (ValueError, TypeError):
        return _DEFAULT_START_WB


async def _next_wb_code(session: AsyncSession, tenant_id: int) -> str:
    raw = await _get_setting(session, tenant_id, _KEY_NEXT_WB)
    try:
        cur = int(raw) if raw else await _get_start_wb(session, tenant_id)
    except (ValueError, TypeError):
        cur = await _get_start_wb(session, tenant_id)
    await _set_setting(session, tenant_id, _KEY_NEXT_WB, str(cur + 1))
    return f"WB_{cur}"


# ── Upload / status ──────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_distribution(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Загрузить файл «Распределение» — НОВАЯ сессия: чистим прошлые данные,
    сбрасываем счётчик WB к стартовому, парсим листы брендов."""
    content = await file.read()
    aliases = await _get_aliases(session, user.tenant_id)
    try:
        parsed = parse_distribution_file(content, aliases)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    rows = parsed["rows"]
    if not rows:
        raise HTTPException(
            400,
            "В файле не найдено строк коробов (нужны листы с колонками "
            "«ШК короба», «Баркод», «Склад», «количество»).",
        )

    tid = user.tenant_id
    # Чистим прошлую сессию (короба + содержимое каскадом).
    await session.execute(
        delete(BoxDistributionWbBox).where(BoxDistributionWbBox.tenant_id == tid)
    )
    await session.execute(
        delete(BoxDistributionSrc).where(BoxDistributionSrc.tenant_id == tid)
    )
    # Сброс счётчика к стартовому.
    start = await _get_start_wb(session, tid)
    await _set_setting(session, tid, _KEY_NEXT_WB, str(start))

    payload = [{"tenant_id": tid, **r} for r in rows]
    for i in range(0, len(payload), 1000):
        await session.execute(
            pg_insert(BoxDistributionSrc).values(payload[i : i + 1000])
        )
    await session.commit()

    return {
        "rows": len(rows),
        "boxes": len({r["src_box_code"] for r in rows}),
        "sheets": parsed["sheets"],
        "skipped": parsed["skipped"],
        "warehouses": _warehouse_summary(rows),
    }


def _warehouse_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        w = r["warehouse"]
        a = agg.setdefault(w, {"warehouse": w, "rows": 0, "raw": set()})
        a["rows"] += 1
        if r.get("warehouse_raw"):
            a["raw"].add(r["warehouse_raw"])
    return [
        {"warehouse": k, "rows": v["rows"], "raw_names": sorted(v["raw"])}
        for k, v in sorted(agg.items(), key=lambda x: -x[1]["rows"])
    ]


@router.get("/status")
async def status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    tid = user.tenant_id
    total_boxes = (
        await session.execute(
            select(func.count(func.distinct(BoxDistributionSrc.src_box_code))).where(
                BoxDistributionSrc.tenant_id == tid
            )
        )
    ).scalar_one()
    # «Обработан» = полностью разложен (Σdistributed_qty ≥ Σqty). Считаем по
    # количествам, а не по флагу distributed (его ставит только force-complete).
    fully_subq = (
        select(BoxDistributionSrc.src_box_code)
        .where(BoxDistributionSrc.tenant_id == tid)
        .group_by(BoxDistributionSrc.src_box_code)
        .having(func.sum(BoxDistributionSrc.qty) > 0)
        .having(
            func.sum(BoxDistributionSrc.distributed_qty)
            >= func.sum(BoxDistributionSrc.qty)
        )
        .subquery()
    )
    distributed_boxes = (
        await session.execute(select(func.count()).select_from(fully_subq))
    ).scalar_one()
    wb_open = (
        await session.execute(
            select(func.count()).where(
                BoxDistributionWbBox.tenant_id == tid,
                BoxDistributionWbBox.status == "open",
            )
        )
    ).scalar_one()
    wb_filled = (
        await session.execute(
            select(func.count()).where(
                BoxDistributionWbBox.tenant_id == tid,
                BoxDistributionWbBox.status == "filled",
            )
        )
    ).scalar_one()
    last_upload = (
        await session.execute(
            select(func.max(BoxDistributionSrc.uploaded_at)).where(
                BoxDistributionSrc.tenant_id == tid
            )
        )
    ).scalar_one()
    return {
        "has_data": bool(total_boxes),
        "total_boxes": int(total_boxes or 0),
        "distributed_boxes": int(distributed_boxes or 0),
        "wb_boxes_open": int(wb_open or 0),
        "wb_boxes_filled": int(wb_filled or 0),
        "uploaded_at": last_upload.isoformat() if last_upload else None,
        "next_wb": await _get_setting(session, tid, _KEY_NEXT_WB),
    }


# ── Scan / distribute ─────────────────────────────────────────────────────────


@router.get("/search")
async def search_boxes(
    q: str = "",
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Полнотекстовый поиск входящего короба по части ШК (напр. «119» →
    ALT-001-236-119). До 25 совпадений с прогрессом раскладки."""
    tid = user.tenant_id
    qq = q.strip()
    if not qq:
        return {"boxes": []}
    rows = (
        await session.execute(
            select(
                BoxDistributionSrc.src_box_code,
                func.max(BoxDistributionSrc.brand).label("brand"),
                func.sum(BoxDistributionSrc.qty).label("total"),
                func.sum(BoxDistributionSrc.distributed_qty).label("done"),
            )
            .where(
                BoxDistributionSrc.tenant_id == tid,
                BoxDistributionSrc.src_box_code.ilike(f"%{qq}%"),
            )
            .group_by(BoxDistributionSrc.src_box_code)
            .order_by(BoxDistributionSrc.src_box_code)
            .limit(25)
        )
    ).all()
    out = []
    for code, brand, total, done in rows:
        t, d = int(total or 0), int(done or 0)
        out.append(
            {
                "src_box_code": code,
                "brand": brand,
                "total_qty": t,
                "distributed_qty": d,
                "status": "full" if d >= t and t > 0 else "partial" if d > 0 else "none",
            }
        )
    return {"boxes": out}


@router.get("/scan/{box_code}")
async def scan_box(
    box_code: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Найти входящий короб по ШК (точное совпадение) → аллокации по складам +
    текущий открытый WB-короб для каждого склада."""
    tid = user.tenant_id
    code = box_code.strip()
    rows = (
        (
            await session.execute(
                select(BoxDistributionSrc).where(
                    BoxDistributionSrc.tenant_id == tid,
                    BoxDistributionSrc.src_box_code == code,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(404, f"Короб «{code}» не найден в загруженном файле")

    # текущие открытые WB-короба по складам
    open_boxes = (
        (
            await session.execute(
                select(BoxDistributionWbBox).where(
                    BoxDistributionWbBox.tenant_id == tid,
                    BoxDistributionWbBox.status == "open",
                )
            )
        )
        .scalars()
        .all()
    )
    open_by_wh = {b.warehouse: b for b in open_boxes}

    # Агрегируем остатки по (склад, баркод): remaining = Σqty − Σdistributed_qty.
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    total_qty = 0
    total_done = 0
    for r in rows:
        total_qty += r.qty
        total_done += r.distributed_qty
        k = (r.warehouse, r.barcode)
        a = agg.setdefault(
            k,
            {
                "warehouse": r.warehouse,
                "barcode": r.barcode,
                "vendor_article": r.vendor_article,
                "size": r.size,
                "qty": 0,
                "done": 0,
            },
        )
        a["qty"] += r.qty
        a["done"] += r.distributed_qty

    by_wh: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in agg.values():
        remaining = a["qty"] - a["done"]
        if remaining <= 0:
            continue
        by_wh[a["warehouse"]].append(
            {
                "barcode": a["barcode"],
                "vendor_article": a["vendor_article"],
                "size": a["size"],
                "qty": a["qty"],  # исходное кол-во
                "qty_done": a["done"],  # уже разложено
                "qty_suggested": remaining,  # остаток к раскладке
            }
        )

    placements = []
    for wh in sorted(by_wh):
        ob = open_by_wh.get(wh)
        placements.append(
            {
                "warehouse": wh,
                "open_wb_box_id": ob.id if ob else None,
                "open_wb_box_code": ob.wb_box_code if ob else None,
                "items": by_wh[wh],
            }
        )
    fully = total_done >= total_qty and total_qty > 0
    return {
        "src_box_code": code,
        "brand": rows[0].brand,
        "fully_distributed": fully or all(r.distributed for r in rows),
        "total_qty": total_qty,
        "distributed_qty": total_done,
        "placements": placements,
    }


class DistributeItem(BaseModel):
    barcode: str
    qty: int = Field(ge=0)


class DistributePlacement(BaseModel):
    warehouse: str
    items: list[DistributeItem]


class DistributeRequest(BaseModel):
    src_box_code: str
    placements: list[DistributePlacement]


async def _record_distributed(
    session: AsyncSession, tid: int, src_box_code: str, warehouse: str, barcode: str, qty: int
) -> int:
    """Записать факт раскладки в src-строки (cap на остаток). Возвращает реально
    записанное кол-во (≤ остатка) — запрет повторной/избыточной раскладки."""
    if qty <= 0:
        return 0
    rows = (
        (
            await session.execute(
                select(BoxDistributionSrc).where(
                    BoxDistributionSrc.tenant_id == tid,
                    BoxDistributionSrc.src_box_code == src_box_code,
                    BoxDistributionSrc.warehouse == warehouse,
                    BoxDistributionSrc.barcode == barcode,
                )
            )
        )
        .scalars()
        .all()
    )
    left = qty
    recorded = 0
    for r in rows:
        if left <= 0:
            break
        can = r.qty - r.distributed_qty
        if can <= 0:
            continue
        add = min(can, left)
        r.distributed_qty += add
        left -= add
        recorded += add
    return recorded


@router.post("/distribute")
async def distribute(
    body: DistributeRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Разложить товары входящего короба в WB-короба (по складам, накопительно).

    Кол-во capится на остаток (qty − distributed_qty) — нельзя распределить дважды
    или больше, чем в коробе. В WB-короб уходит реально записанное кол-во."""
    tid = user.tenant_id
    affected: list[int] = []
    for pl in body.placements:
        # реально записываемые позиции (cap на остаток)
        placed: list[tuple[str, int]] = []
        for it in pl.items:
            rec = await _record_distributed(
                session, tid, body.src_box_code, pl.warehouse, it.barcode, it.qty
            )
            if rec > 0:
                placed.append((it.barcode, rec))
        if not placed:
            continue
        box = (
            await session.execute(
                select(BoxDistributionWbBox).where(
                    BoxDistributionWbBox.tenant_id == tid,
                    BoxDistributionWbBox.warehouse == pl.warehouse,
                    BoxDistributionWbBox.status == "open",
                )
            )
        ).scalar_one_or_none()
        if box is None:
            code = await _next_wb_code(session, tid)
            box = BoxDistributionWbBox(
                tenant_id=tid, wb_box_code=code, warehouse=pl.warehouse, status="open"
            )
            session.add(box)
            await session.flush()
        for barcode, qty in placed:
            stmt = pg_insert(BoxDistributionWbItem).values(
                tenant_id=tid, wb_box_id=box.id, barcode=barcode, qty=qty
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["wb_box_id", "barcode"],
                set_={
                    "qty": BoxDistributionWbItem.__table__.c.qty + stmt.excluded.qty
                },
            )
            await session.execute(stmt)
        affected.append(box.id)

    await session.commit()
    return {"affected_wb_box_ids": affected}


@router.post("/wb-box/{box_id}/fill")
async def fill_wb_box(
    box_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    box = (
        await session.execute(
            select(BoxDistributionWbBox).where(
                BoxDistributionWbBox.tenant_id == user.tenant_id,
                BoxDistributionWbBox.id == box_id,
            )
        )
    ).scalar_one_or_none()
    if box is None:
        raise HTTPException(404, "WB-короб не найден")
    box.status = "filled"
    await session.commit()
    return {"id": box.id, "status": box.status}


@router.post("/src/{box_code}/distributed")
async def mark_distributed(
    box_code: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Принудительно завершить короб: distributed=True + distributed_qty=qty
    (остаток списывается — короб больше не предлагается)."""
    res = await session.execute(
        BoxDistributionSrc.__table__.update()
        .where(
            BoxDistributionSrc.tenant_id == user.tenant_id,
            BoxDistributionSrc.src_box_code == box_code.strip(),
        )
        .values(distributed=True, distributed_qty=BoxDistributionSrc.__table__.c.qty)
    )
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(404, f"Короб «{box_code}» не найден")
    return {"src_box_code": box_code.strip(), "distributed": True}


@router.get("/distributed-boxes")
async def distributed_boxes(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список уже затронутых раскладкой входящих коробов (full/partial)."""
    tid = user.tenant_id
    rows = (
        await session.execute(
            select(
                BoxDistributionSrc.src_box_code,
                func.max(BoxDistributionSrc.brand).label("brand"),
                func.sum(BoxDistributionSrc.qty).label("total"),
                func.sum(BoxDistributionSrc.distributed_qty).label("done"),
            )
            .where(BoxDistributionSrc.tenant_id == tid)
            .group_by(BoxDistributionSrc.src_box_code)
            .having(func.sum(BoxDistributionSrc.distributed_qty) > 0)
            .order_by(BoxDistributionSrc.src_box_code)
        )
    ).all()
    return {
        "boxes": [
            {
                "src_box_code": code,
                "brand": brand,
                "total_qty": int(total or 0),
                "distributed_qty": int(done or 0),
                "status": "full" if int(done or 0) >= int(total or 0) else "partial",
            }
            for code, brand, total, done in rows
        ]
    }


@router.post("/reset")
async def reset_distribution(
    confirm: bool = False,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сбросить ВСЕ раскладки (WB-короба + distributed_qty) и счётчик к старту.
    Исходный файл остаётся. Требует confirm=true (доп. подтверждение)."""
    if not confirm:
        raise HTTPException(400, "Нужно подтверждение: confirm=true")
    tid = user.tenant_id
    await session.execute(
        delete(BoxDistributionWbBox).where(BoxDistributionWbBox.tenant_id == tid)
    )
    await session.execute(
        BoxDistributionSrc.__table__.update()
        .where(BoxDistributionSrc.tenant_id == tid)
        .values(distributed=False, distributed_qty=0)
    )
    start = await _get_start_wb(session, tid)
    await _set_setting(session, tid, _KEY_NEXT_WB, str(start))
    await session.commit()
    return {"ok": True, "next_wb": start}


# ── WB boxes review / manual edit ─────────────────────────────────────────────


@router.get("/wb-boxes")
async def list_wb_boxes(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    tid = user.tenant_id
    boxes = (
        (
            await session.execute(
                select(BoxDistributionWbBox)
                .where(BoxDistributionWbBox.tenant_id == tid)
                .order_by(BoxDistributionWbBox.id)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await session.execute(
                select(BoxDistributionWbItem).where(
                    BoxDistributionWbItem.tenant_id == tid
                )
            )
        )
        .scalars()
        .all()
    )
    items_by_box: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        items_by_box[it.wb_box_id].append(
            {"id": it.id, "barcode": it.barcode, "qty": it.qty}
        )
    return {
        "boxes": [
            {
                "id": b.id,
                "wb_box_code": b.wb_box_code,
                "warehouse": b.warehouse,
                "status": b.status,
                "items": items_by_box.get(b.id, []),
            }
            for b in boxes
        ]
    }


class WbItemEdit(BaseModel):
    barcode: str
    qty: int = Field(ge=0)  # qty=0 → удалить строку


class WbItemsPatch(BaseModel):
    items: list[WbItemEdit]


@router.patch("/wb-box/{box_id}/items")
async def patch_wb_items(
    box_id: int,
    body: WbItemsPatch,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    tid = user.tenant_id
    box = (
        await session.execute(
            select(BoxDistributionWbBox).where(
                BoxDistributionWbBox.tenant_id == tid,
                BoxDistributionWbBox.id == box_id,
            )
        )
    ).scalar_one_or_none()
    if box is None:
        raise HTTPException(404, "WB-короб не найден")
    for it in body.items:
        if it.qty <= 0:
            await session.execute(
                delete(BoxDistributionWbItem).where(
                    BoxDistributionWbItem.tenant_id == tid,
                    BoxDistributionWbItem.wb_box_id == box_id,
                    BoxDistributionWbItem.barcode == it.barcode,
                )
            )
            continue
        stmt = pg_insert(BoxDistributionWbItem).values(
            tenant_id=tid, wb_box_id=box_id, barcode=it.barcode, qty=it.qty
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["wb_box_id", "barcode"],
            set_={"qty": stmt.excluded.qty},  # ручная правка — SET (не +=)
        )
        await session.execute(stmt)
    await session.commit()
    return {"id": box_id, "ok": True}


# ── Warehouses (alias map) ─────────────────────────────────────────────────────


@router.get("/warehouses")
async def list_warehouses(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    tid = user.tenant_id
    rows = (
        await session.execute(
            select(
                BoxDistributionSrc.warehouse,
                BoxDistributionSrc.warehouse_raw,
                func.count().label("n"),
            )
            .where(BoxDistributionSrc.tenant_id == tid)
            .group_by(BoxDistributionSrc.warehouse, BoxDistributionSrc.warehouse_raw)
        )
    ).all()
    agg: dict[str, dict[str, Any]] = {}
    for canon, raw, n in rows:
        a = agg.setdefault(canon, {"warehouse": canon, "rows": 0, "raw_names": set()})
        a["rows"] += int(n)
        if raw:
            a["raw_names"].add(raw)
    return {
        "warehouses": [
            {"warehouse": k, "rows": v["rows"], "raw_names": sorted(v["raw_names"])}
            for k, v in sorted(agg.items(), key=lambda x: -x[1]["rows"])
        ],
        "aliases": await _get_aliases(session, tid),
        "seed_aliases": WAREHOUSE_ALIASES_SEED,
    }


class AliasesPut(BaseModel):
    aliases: dict[str, str]


@router.put("/warehouses/aliases")
async def put_aliases(
    body: AliasesPut,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сохранить пользовательскую карту слияния складов и пере-нормализовать
    уже загруженные строки (warehouse из warehouse_raw по новой карте)."""
    tid = user.tenant_id
    await _set_setting(session, tid, _KEY_ALIASES, json.dumps(body.aliases, ensure_ascii=False))
    # пере-нормализация существующих строк
    rows = (
        (
            await session.execute(
                select(BoxDistributionSrc).where(BoxDistributionSrc.tenant_id == tid)
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        r.warehouse = normalize_warehouse(r.warehouse_raw or r.warehouse, body.aliases)
    await session.commit()
    return {"ok": True, "rows_renormalized": len(rows)}


# ── Export ─────────────────────────────────────────────────────────────────────


@router.get("/export.xlsx")
async def export_xlsx(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    """Сгенерировать shk-excel по всем WB-коробам (open+filled)."""
    tid = user.tenant_id
    boxes = (
        (
            await session.execute(
                select(BoxDistributionWbBox)
                .where(BoxDistributionWbBox.tenant_id == tid)
                .order_by(BoxDistributionWbBox.id)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await session.execute(
                select(BoxDistributionWbItem).where(
                    BoxDistributionWbItem.tenant_id == tid
                )
            )
        )
        .scalars()
        .all()
    )
    code_by_box = {b.id: b.wb_box_code for b in boxes}
    items_by_box: dict[int, list[BoxDistributionWbItem]] = defaultdict(list)
    for it in items:
        items_by_box[it.wb_box_id].append(it)
    out_rows: list[dict[str, Any]] = []
    for b in boxes:
        for it in sorted(items_by_box.get(b.id, []), key=lambda x: x.barcode):
            out_rows.append(
                {"barcode": it.barcode, "qty": it.qty, "wb_box_code": code_by_box[b.id]}
            )
    xlsx = build_shk_xlsx(out_rows)
    return Response(
        content=xlsx,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="shk-export.xlsx"'},
    )
