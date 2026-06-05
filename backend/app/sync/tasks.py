"""Celery tasks for syncing data from Wildberries.

Each task:
  1. opens an async session and a WB API client
  2. fetches incremental data via the integrations layer
  3. upserts rows
  4. updates the sync_checkpoints row

Tasks are sync wrappers around async coroutines (run via asyncio.run) so they are
plain Celery tasks but the I/O underneath is non-blocking httpx + asyncpg.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil.parser import isoparse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbOrder,
    WbPaidStorage,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.db.session import task_session_scope as session_scope
from app.integrations.wb import WbApiClient
from app.integrations.wb.advert import (
    fetch_campaign_ids,  # noqa: F401  (kept for backward compatibility)
    fetch_campaigns_info,
    fetch_campaigns_overview,
    fetch_fullstats,
)
from app.integrations.wb.paid_storage import fetch_paid_storage
from app.integrations.wb.statistics import (
    fetch_orders,
    fetch_report_detail_with_fallback as fetch_report_detail_v2,
    fetch_sales,
    fetch_stocks_with_fallback as fetch_stocks,
)
from app.sync.celery_app import celery_app
from app.sync.checkpoints import get_date_from, update_checkpoint
from app.sync.tenants import (
    get_active_tenants,
    get_tenant_token,
    tenant_sync_context,
)
from app.services.tenant_context import set_tenant


async def _list_active_tenants() -> list[int]:
    """Helper для dispatcher'ов: список tenants с WB-токеном.

    ВАЖНО: используем `task_session_scope`, а не модульный `session_scope`.
    Модульный engine привязан к event loop процесса (FastAPI loop №1).
    Celery worker внутри `asyncio.run(...)` создаёт **новый** loop №2 —
    реюз модульного engine из другого loop'а даёт
    `RuntimeError: Future ... attached to a different loop` через раз.
    `task_session_scope` создаёт fresh engine внутри текущего loop'а.
    """
    from app.db.session import task_session_scope as _ss  # noqa: WPS433

    async with _ss() as session:
        return await get_active_tenants(session)


def _fanout(per_tenant_task, *task_args: Any) -> dict[str, Any]:
    """Запустить per-tenant task для каждого активного tenant'а."""
    tenants = asyncio.run(_list_active_tenants())
    if not tenants:
        log.info("dispatcher: no active tenants (no WB token set)")
        return {"tenants_scheduled": 0}
    for tid in tenants:
        per_tenant_task.delay(tid, *task_args)
    return {"tenants_scheduled": len(tenants), "tenant_ids": tenants}

log = get_logger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return isoparse(str(value))
    except (ValueError, TypeError):
        return None


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce WB-API value → Decimal | None. Empty strings / None → None.
    WB отдаёт денежные поля строками вроде "0", "82.999", "-167.17131114";
    проценты — числами. Передавать "" в Numeric колонку asyncpg не умеет."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    return None


# asyncpg / Postgres binary protocol limit: max 32767 bind parameters per query.
# Pick a chunk size that keeps us well under that even for the widest table.
# After report_detail expansion to 88 cols (2026-05) 1000-row chunks would
# blow the limit (88000 params), so bulk helpers auto-shrink based on the
# actual number of columns per row.
_BULK_CHUNK_ROWS = 1000
_PARAM_LIMIT = 30000  # safety margin under 32767


def _stamp_tenant(session: AsyncSession, model: Any, values: list[dict[str, Any]]) -> None:
    """Auto-проставить tenant_id в values если:
      1) сессия знает tenant_id (set_tenant() был вызван), и
      2) модель имеет колонку tenant_id (наследник TenantScopedMixin).

    Это нужно потому что Core pg_insert(...).values(...) минует ORM events,
    поэтому before_flush hook не срабатывает. Помещаем tenant_id явно в dict.
    """
    tid = session.sync_session.info.get("tenant_id")
    if tid is None:
        return
    if not hasattr(model, "tenant_id"):
        return
    for row in values:
        row.setdefault("tenant_id", tid)


def _safe_chunk_size(first_row: dict[str, Any]) -> int:
    """Подобрать chunk size так чтобы chunk × cols < _PARAM_LIMIT.
    Для широких таблиц (report_detail ~85 cols) даёт ~350 строк за один
    INSERT; для узких остаётся cap = _BULK_CHUNK_ROWS."""
    ncols = max(len(first_row), 1)
    return max(1, min(_BULK_CHUNK_ROWS, _PARAM_LIMIT // ncols))


async def _bulk_upsert(
    session: AsyncSession,
    model: Any,
    values: list[dict[str, Any]],
    *,
    pk_cols: list[str],
) -> None:
    """Upsert `values` into `model` in chunks to stay below the asyncpg
    32767-parameter limit. `pk_cols` define the conflict target; all other
    columns get overwritten by the new row."""
    if not values:
        return
    _stamp_tenant(session, model, values)
    chunk_rows = _safe_chunk_size(values[0])
    for start in range(0, len(values), chunk_rows):
        chunk = values[start : start + chunk_rows]
        stmt = pg_insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=pk_cols,
            set_={c.name: c for c in stmt.excluded if c.name not in pk_cols},
        )
        await session.execute(stmt)


async def _bulk_insert(
    session: AsyncSession,
    model: Any,
    values: list[dict[str, Any]],
) -> None:
    """Plain chunked insert (no conflict resolution) for tables we just
    truncated for the date range — e.g. snapshots that get fully replaced."""
    if not values:
        return
    _stamp_tenant(session, model, values)
    chunk_rows = _safe_chunk_size(values[0])
    for start in range(0, len(values), chunk_rows):
        chunk = values[start : start + chunk_rows]
        await session.execute(pg_insert(model).values(chunk))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return isoparse(str(value)).date()
    except (ValueError, TypeError):
        return None


async def _ensure_products(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc)
    seen: dict[int, dict[str, Any]] = {}
    for r in rows:
        nm = r.get("nmId") or r.get("nm_id")
        if nm is None:
            continue
        seen[int(nm)] = {
            "nm_id": int(nm),
            "vendor_code": r.get("supplierArticle") or r.get("sa_name"),
            "subject": r.get("subject"),
            "brand": r.get("brand"),
            "category": r.get("category"),
            "last_seen_at": now,
            # Re-appearance auto-unarchives the SKU. archived_at is intentionally
            # not cleared on conflict — that only happens through the explicit
            # unarchive endpoint, so we keep the historical timestamp of the last
            # archival in case of churn.
            "is_archived": False,
        }
    if not seen:
        return
    rows = list(seen.values())
    _stamp_tenant(session, Product, rows)
    for start in range(0, len(rows), _BULK_CHUNK_ROWS):
        chunk = rows[start : start + _BULK_CHUNK_ROWS]
        stmt = pg_insert(Product).values(chunk)
        # COALESCE keeps existing non-NULL values when the syncing source doesn't
        # supply them. Critical for report_detail / backfill which pass only
        # nmId + supplierArticle — without COALESCE these would null out brand /
        # subject / category every run, leaving brand-filter broken for the
        # ~8h window until the next stocks sync restores them.
        stmt = stmt.on_conflict_do_update(
            index_elements=["nm_id"],
            set_={
                "vendor_code": func.coalesce(stmt.excluded.vendor_code, Product.vendor_code),
                "subject": func.coalesce(stmt.excluded.subject, Product.subject),
                "brand": func.coalesce(stmt.excluded.brand, Product.brand),
                "category": func.coalesce(stmt.excluded.category, Product.category),
                "last_seen_at": stmt.excluded.last_seen_at,
                # Re-appearance unarchives — keep unconditional.
                "is_archived": stmt.excluded.is_archived,
            },
        )
        await session.execute(stmt)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def _sync_orders_async(tenant_id: int) -> int:
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("orders: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        date_from = await get_date_from(session, "orders")
        try:
            rows = await fetch_orders(wb, date_from=date_from, flag=0)
        except Exception as e:
            log.warning("orders: fetch failed (%s) — skipping this run", e)
            await update_checkpoint(
                session, "orders", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
        if not rows:
            await update_checkpoint(session, "orders", rows_processed=0)
            return 0

        await _ensure_products(session, rows)

        values = []
        max_lcd: datetime | None = None
        for r in rows:
            srid = r.get("srid")
            if not srid:
                continue
            lcd = _parse_dt(r.get("lastChangeDate"))
            if lcd and (max_lcd is None or lcd > max_lcd):
                max_lcd = lcd
            values.append(
                {
                    "srid": str(srid),
                    "order_dt": _parse_dt(r.get("date")),
                    "last_change_date": lcd,
                    "nm_id": int(r.get("nmId") or 0),
                    "supplier_article": r.get("supplierArticle"),
                    "barcode": r.get("barcode"),
                    "total_price": r.get("totalPrice") or 0,
                    "discount_percent": r.get("discountPercent") or 0,
                    "spp": r.get("spp") or 0,
                    "finished_price": r.get("finishedPrice"),
                    "price_with_disc": r.get("priceWithDisc"),
                    "is_cancel": bool(r.get("isCancel")),
                    "cancel_dt": _parse_dt(r.get("cancelDate")),
                    "warehouse_name": r.get("warehouseName"),
                    "oblast": r.get("oblastOkrugName") or r.get("oblast"),
                    "region_name": r.get("regionName"),
                    "category": r.get("category"),
                    "subject": r.get("subject"),
                    "brand": r.get("brand"),
                    "is_supply": bool(r.get("isSupply")),
                    "is_realization": bool(r.get("isRealization")),
                    "chrt_id": int(r["chrtId"]) if r.get("chrtId") else None,
                    "tech_size": r.get("techSize"),
                }
            )

        await _bulk_upsert(session, WbOrder, values, pk_cols=["srid"])

        await update_checkpoint(
            session, "orders", last_change_date=max_lcd, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_orders_for_tenant")
def sync_orders_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_orders_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_orders")
def sync_orders() -> dict[str, Any]:
    """Beat dispatcher: fanout sync_orders_for_tenant для всех active tenants."""
    return _fanout(sync_orders_for_tenant)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


async def _sync_sales_async(tenant_id: int) -> int:
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("sales: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        date_from = await get_date_from(session, "sales")
        try:
            rows = await fetch_sales(wb, date_from=date_from, flag=0)
        except Exception as e:
            log.warning("sales: fetch failed (%s) — skipping this run", e)
            await update_checkpoint(
                session, "sales", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
        if not rows:
            await update_checkpoint(session, "sales", rows_processed=0)
            return 0

        await _ensure_products(session, rows)

        values = []
        max_lcd: datetime | None = None
        for r in rows:
            sale_id = r.get("saleID")
            if not sale_id:
                continue
            lcd = _parse_dt(r.get("lastChangeDate"))
            if lcd and (max_lcd is None or lcd > max_lcd):
                max_lcd = lcd
            values.append(
                {
                    "sale_id": str(sale_id),
                    "srid": r.get("srid"),
                    "sale_dt": _parse_dt(r.get("date")),
                    "last_change_date": lcd,
                    "nm_id": int(r.get("nmId") or 0),
                    "supplier_article": r.get("supplierArticle"),
                    "total_price": r.get("totalPrice") or 0,
                    "discount_percent": r.get("discountPercent") or 0,
                    "spp": r.get("spp") or 0,
                    "price_with_disc": r.get("priceWithDisc"),
                    "for_pay": r.get("forPay") or 0,
                    "finished_price": r.get("finishedPrice"),
                    "commission_percent": r.get("commissionPercent") or 0,
                    "is_return": str(sale_id).startswith("R"),
                    "warehouse_name": r.get("warehouseName"),
                    "region_name": r.get("regionName"),
                    "oblast": r.get("oblastOkrugName") or r.get("oblast"),
                    "chrt_id": int(r["chrtId"]) if r.get("chrtId") else None,
                    "tech_size": r.get("techSize"),
                }
            )

        await _bulk_upsert(session, WbSale, values, pk_cols=["sale_id"])

        await update_checkpoint(
            session, "sales", last_change_date=max_lcd, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_sales_for_tenant")
def sync_sales_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_sales_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_sales")
def sync_sales() -> dict[str, Any]:
    return _fanout(sync_sales_for_tenant)


# ---------------------------------------------------------------------------
# Stocks (full snapshot, written with current timestamp)
# ---------------------------------------------------------------------------


async def _sync_stocks_async(tenant_id: int) -> int:
    snapshot_dt = datetime.now(timezone.utc).replace(microsecond=0)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("stocks: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        try:
            rows = await fetch_stocks(wb)
        except Exception as e:
            log.warning("stocks: fetch failed (%s) — skipping this run", e)
            await update_checkpoint(
                session, "stocks", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
        if not rows:
            await update_checkpoint(session, "stocks", rows_processed=0)
            return 0

        await _ensure_products(session, rows)

        # keep only the latest snapshot per nm_id+warehouse for the same calendar day
        # (we still keep historical snapshots from previous days)
        today_start = snapshot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        await session.execute(
            delete(WbStockSnapshot).where(WbStockSnapshot.snapshot_dt >= today_start)
        )

        values = []
        for r in rows:
            nm = r.get("nmId")
            if nm is None:
                continue
            values.append(
                {
                    "snapshot_dt": snapshot_dt,
                    "nm_id": int(nm),
                    "barcode": r.get("barcode"),
                    "supplier_article": r.get("supplierArticle"),
                    "warehouse_name": r.get("warehouseName"),
                    "quantity": int(r.get("quantity") or 0),
                    "in_way_to_client": int(r.get("inWayToClient") or 0),
                    "in_way_from_client": int(r.get("inWayFromClient") or 0),
                    "quantity_full": int(r.get("quantityFull") or 0),
                    "price": r.get("Price") or r.get("price"),
                    "discount": r.get("Discount") or r.get("discount"),
                    "chrt_id": int(r["chrtId"]) if r.get("chrtId") else None,
                    "tech_size": r.get("techSize"),
                }
            )
        await _bulk_insert(session, WbStockSnapshot, values)

        await update_checkpoint(
            session, "stocks", last_change_date=snapshot_dt, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_stocks_for_tenant")
def sync_stocks_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_stocks_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_stocks")
def sync_stocks() -> dict[str, Any]:
    return _fanout(sync_stocks_for_tenant)


# ---------------------------------------------------------------------------
# Paid storage (per-SKU/per-day storage cost)
# ---------------------------------------------------------------------------


async def _sync_paid_storage_async(tenant_id: int, days_back: int = 7) -> int:
    """Тянем `paid_storage` за последние `days_back` дней и upsert по
    (date, nm_id, chrt_id, warehouse). Окно WB до 8 дней включительно;
    дефолтный sync = 7 дней (с запасом перекрытия).
    """
    end_date = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start_date = (end_date - timedelta(days=days_back)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("paid_storage: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        try:
            rows = await fetch_paid_storage(wb, date_from=start_date, date_to=end_date)
        except Exception as e:
            log.warning("paid_storage: fetch failed (%s) — skipping this run", e)
            await update_checkpoint(
                session, "paid_storage", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
        if not rows:
            await update_checkpoint(session, "paid_storage", rows_processed=0)
            return 0

        # WB иногда возвращает несколько строк за один (date, nm_id, chrt_id,
        # warehouse) — разный officeId/calc_type/тарифы. Склеиваем через
        # суммирование warehousePrice и barcodesCount, остальные поля — из
        # первой встретившейся строки.
        agg: dict[tuple, dict[str, Any]] = {}
        for r in rows:
            nm_id_raw = r.get("nmId")
            if not nm_id_raw:
                continue
            d = _parse_date(r.get("date")) or _parse_date(r.get("originalDate"))
            if d is None:
                continue
            # NULL в составном UNIQUE constraint ломает ON CONFLICT в Postgres
            # (NULL != NULL). Подменяем на 0/«—» — у WB chrtId/warehouse
            # фактически всегда есть, но defensively cover edge cases.
            chrt = int(r["chrtId"]) if r.get("chrtId") else 0
            warehouse = r.get("warehouse") or "—"
            key = (d, int(nm_id_raw), chrt, warehouse)
            if key in agg:
                agg[key]["warehouse_price"] = float(agg[key]["warehouse_price"]) + float(
                    r.get("warehousePrice") or 0
                )
                agg[key]["barcodes_count"] = int(agg[key]["barcodes_count"]) + int(
                    r.get("barcodesCount") or 0
                )
                continue
            agg[key] = {
                "date": d,
                "nm_id": int(nm_id_raw),
                "chrt_id": chrt,
                "tech_size": r.get("size"),
                "barcode": r.get("barcode"),
                "vendor_code": r.get("vendorCode"),
                "brand": r.get("brand"),
                "subject": r.get("subject"),
                "warehouse": warehouse,
                "office_id": int(r["officeId"]) if r.get("officeId") else None,
                "calc_type": r.get("calcType"),
                "warehouse_price": float(r.get("warehousePrice") or 0),
                "barcodes_count": int(r.get("barcodesCount") or 0),
                "volume": r.get("volume"),
                "warehouse_coef": r.get("warehouseCoef"),
                "log_warehouse_coef": r.get("logWarehouseCoef"),
                "loyalty_discount": r.get("loyaltyDiscount"),
                "pallet_place_code": (
                    str(r["palletPlaceCode"])
                    if r.get("palletPlaceCode") not in (None, "")
                    else None
                ),
                "pallet_count": int(r["palletCount"]) if r.get("palletCount") not in (None, "") else None,
                "original_date": _parse_date(r.get("originalDate")),
                "tariff_fix_date": _parse_date(r.get("tariffFixDate")),
                "tariff_lower_date": _parse_date(r.get("tariffLowerDate")),
            }
        values: list[dict[str, Any]] = list(agg.values())

        await _bulk_upsert(
            session,
            WbPaidStorage,
            values,
            pk_cols=["date", "nm_id", "chrt_id", "warehouse"],
        )
        await update_checkpoint(session, "paid_storage", rows_processed=len(values))
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_paid_storage_for_tenant")
def sync_paid_storage_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_paid_storage_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_paid_storage")
def sync_paid_storage() -> dict[str, Any]:
    return _fanout(sync_paid_storage_for_tenant)


# ---------------------------------------------------------------------------
# Report Detail (source of truth for P&L)
# ---------------------------------------------------------------------------


async def _sync_report_detail_async(tenant_id: int, days_back: int = 14) -> int:
    """Re-pull report detail for the last `days_back` days (rows continue arriving)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    total = 0
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("report_detail: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        try:
            chunks_iter = fetch_report_detail_v2(wb, date_from=start, date_to=end)
        except Exception as e:
            log.warning("report_detail: fetch failed (%s) — skipping this run", e)
            await update_checkpoint(
                session, "report_detail", rows_processed=0,
                status="skipped", error=str(e)[:500],
            )
            return 0
        try:
            async for chunk in chunks_iter:
                await _ensure_products(
                    session,
                    [
                        {"nmId": r.get("nm_id"), "supplierArticle": r.get("sa_name")}
                        for r in chunk
                        if r.get("nm_id")
                    ],
                )
                values = []
                for r in chunk:
                    rrd = r.get("rrd_id")
                    if rrd is None:
                        continue
                    values.append(
                        {
                            # === PK ===
                            "rrd_id": int(rrd),
                            # === Existing ~30 fields ===
                            "realization_id": _to_int(r.get("realizationreport_id")),
                            "report_date_from": _parse_date(r.get("date_from")),
                            "report_date_to": _parse_date(r.get("date_to")),
                            "create_dt": _parse_date(r.get("create_dt")),
                            "nm_id": _to_int(r.get("nm_id")),
                            "sa_name": r.get("sa_name"),
                            "barcode": r.get("barcode"),
                            "doc_type_name": r.get("doc_type_name"),
                            "supplier_oper_name": r.get("supplier_oper_name"),
                            "order_dt": _parse_dt(r.get("order_dt")),
                            "sale_dt": _parse_dt(r.get("sale_dt")),
                            "rr_dt": _parse_date(r.get("rr_dt")),
                            "quantity": _to_int(r.get("quantity")) or 0,
                            "retail_price": _to_decimal(r.get("retail_price")) or 0,
                            "retail_amount": _to_decimal(r.get("retail_amount")) or 0,
                            "sale_percent": _to_decimal(r.get("sale_percent")) or 0,
                            "commission_percent": _to_decimal(r.get("commission_percent")) or 0,
                            "ppvz_for_pay": _to_decimal(r.get("ppvz_for_pay")) or 0,
                            "delivery_rub": _to_decimal(r.get("delivery_rub")) or 0,
                            "storage_fee": _to_decimal(r.get("storage_fee")) or 0,
                            "penalty": _to_decimal(r.get("penalty")) or 0,
                            "additional_payment": _to_decimal(r.get("additional_payment")) or 0,
                            "deduction": _to_decimal(r.get("deduction")) or 0,
                            "acquiring_fee": _to_decimal(r.get("acquiring_fee")) or 0,
                            "retail_price_withdisc_rub": _to_decimal(r.get("retail_price_withdisc_rub")),
                            "kiz": r.get("kiz") or None,
                            "ppvz_vw": _to_decimal(r.get("ppvz_vw")),
                            "ppvz_vw_nds": _to_decimal(r.get("ppvz_vw_nds")),
                            "supplier_reward": _to_decimal(r.get("supplier_reward")),  # legacy, новый API не отдаёт
                            # === New 58 fields (migration 0017, 2026-05) ===
                            # Strings
                            "acquiring_bank": r.get("acquiring_bank"),
                            "article_substitution": r.get("article_substitution") or None,
                            "bonus_type_name": r.get("bonus_type_name"),
                            "brand_name": r.get("brand_name"),
                            "country": r.get("country"),
                            "currency": r.get("currency"),
                            "declaration_number": r.get("declaration_number") or None,
                            "delivery_method": r.get("delivery_method") or None,
                            "fix_tariff_date_from": r.get("fix_tariff_date_from") or None,
                            "fix_tariff_date_to": r.get("fix_tariff_date_to") or None,
                            "gi_box_type_name": r.get("gi_box_type_name"),
                            "office_name": r.get("office_name") or None,
                            "order_uid": r.get("order_uid"),
                            "payment_processing": r.get("payment_processing"),
                            "ppvz_office_name": r.get("ppvz_office_name"),
                            "ppvz_supplier_inn": r.get("ppvz_supplier_inn") or None,
                            "ppvz_supplier_name": r.get("ppvz_supplier_name") or None,
                            "srid": r.get("srid"),
                            "sticker_id": r.get("sticker_id") or None,
                            "subject_name": r.get("subject_name"),
                            "tech_size": r.get("tech_size") or None,
                            "title": r.get("title"),
                            "trbx_id": r.get("trbx_id") or None,
                            "uuid_promocode": r.get("uuid_promocode") or None,
                            "vendor_code": r.get("vendor_code"),
                            # BigInt IDs
                            "gi_id": _to_int(r.get("gi_id")),
                            "order_id": _to_int(r.get("order_id")),
                            "ppvz_office_id": _to_int(r.get("ppvz_office_id")),
                            "shk_id": _to_int(r.get("shk_id")),
                            "loyalty_id": _to_int(r.get("loyalty_id")),
                            "seller_promo_id": _to_int(r.get("seller_promo_id")),
                            # Small ints / enums
                            "report_type": _to_int(r.get("report_type")),
                            "is_kgvp_v2": _to_int(r.get("is_kgvp_v2")),
                            "sup_rating_up": _to_int(r.get("sup_rating_up")),
                            "wibes_discount_percent": _to_decimal(r.get("wibes_discount_percent")),
                            # Numerics
                            "acquiring_percent": _to_decimal(r.get("acquiring_percent")),
                            "cashback_amount": _to_decimal(r.get("cashback_amount")),
                            "cashback_commission_change": _to_decimal(r.get("cashback_commission_change")),
                            "cashback_discount": _to_decimal(r.get("cashback_discount")),
                            "delivery_amount": _to_decimal(r.get("delivery_amount")),
                            "dlv_prc": _to_decimal(r.get("dlv_prc")),
                            "installment_cofinancing_amount": _to_decimal(r.get("installment_cofinancing_amount")),
                            "kvw": _to_decimal(r.get("kvw")),
                            "kvw_base": _to_decimal(r.get("kvw_base")),
                            "loyalty_discount": _to_decimal(r.get("loyalty_discount")),
                            "paid_acceptance": _to_decimal(r.get("paid_acceptance")),
                            "payment_schedule": _to_decimal(r.get("payment_schedule")),
                            "ppvz_reward": _to_decimal(r.get("ppvz_reward")),
                            "ppvz_sales_commission": _to_decimal(r.get("ppvz_sales_commission")),
                            "product_discount_for_report": _to_decimal(r.get("product_discount_for_report")),
                            "rebill_logistic_cost": _to_decimal(r.get("rebill_logistic_cost")),
                            "return_amount": _to_decimal(r.get("return_amount")),
                            "sale_price_affiliated_discount_prc": _to_decimal(r.get("sale_price_affiliated_discount_prc")),
                            "sale_price_promocode_discount_prc": _to_decimal(r.get("sale_price_promocode_discount_prc")),
                            "sale_price_wholesale_discount_prc": _to_decimal(r.get("sale_price_wholesale_discount_prc")),
                            "seller_promo": _to_decimal(r.get("seller_promo")),
                            "seller_promo_discount": _to_decimal(r.get("seller_promo_discount")),
                            "spp": _to_decimal(r.get("spp")),
                            # Booleans
                            "is_b2b": _to_bool(r.get("is_b2b")),
                            "srv_dbs": _to_bool(r.get("srv_dbs")),
                        }
                    )
                await _bulk_upsert(session, WbReportDetail, values, pk_cols=["rrd_id"])
                total += len(values)
                # TASK-LEAD-131: commit per chunk. Without this, exception в
                # следующей итерации (WB 429 на page N+1) откатывал ВСЕ ранее
                # обработанные chunks — теряли свежие данные при backfill.
                await session.commit()
        except Exception as e:
            log.warning("report_detail: chunk loop aborted (%s) — partial save", e)
            # If a SQL error aborted the transaction, every subsequent
            # statement on this session raises InFailedSQLTransactionError
            # — including update_checkpoint. Rollback first to free the
            # session, otherwise the task crashes with a misleading error
            # and the real cause is lost.
            try:
                await session.rollback()
            except Exception:
                pass
            try:
                await update_checkpoint(
                    session, "report_detail", rows_processed=total,
                    status="skipped", error=str(e)[:500],
                )
            except Exception as ce:
                log.error("report_detail: failed to record checkpoint: %s", ce)
            return total

        await update_checkpoint(session, "report_detail", rows_processed=total)
    return total


@celery_app.task(name="app.sync.tasks.sync_report_detail_for_tenant")
def sync_report_detail_for_tenant(tenant_id: int, days_back: int = 14) -> int:
    return asyncio.run(_sync_report_detail_async(tenant_id, days_back))


@celery_app.task(name="app.sync.tasks.sync_report_detail")
def sync_report_detail_dispatch() -> dict[str, Any]:
    """Beat dispatcher: fanout sync_report_detail_for_tenant для активных tenants."""
    return _fanout(sync_report_detail_for_tenant)


@celery_app.task(name="app.sync.tasks.sync_report_detail_backfill")
def sync_report_detail_backfill_dispatch() -> dict[str, Any]:
    """Weekly safety net: keep the 12-week reconciliation window populated."""
    return _fanout(sync_report_detail_for_tenant, 90)


# ---------------------------------------------------------------------------
# Redeem notifications (Documents API)
# ---------------------------------------------------------------------------


async def _sync_redeem_notifications_async(tenant_id: int, days_back: int = 400) -> int:
    """Sync «Уведомление о выкупе» через WB Documents API.

    1) GET /documents/list?category=redeem-notification — список доступных за период
    2) Для каждого нового (не в БД) — GET /documents/download — скачать ZIP
    3) Парсим XLSX, upsert в wb_redeem_notification

    Используем per-document download (1/10 сек), а не batch (1/5 мин) — у нас
    редко >1-2 новых в неделю, проще без батчинга.
    """
    from app.db.models import WbRedeemNotification
    from app.integrations.wb.documents import (
        CATEGORY_REDEEM_NOTIFICATION,
        download_document,
        list_documents,
        parse_redeem_notification,
    )

    today = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=days_back)

    total_synced = 0
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("redeem_notifications: tenant %s no token, skip", tenant_id)
            return 0
        session, wb = ctx

        try:
            docs = await list_documents(
                wb, CATEGORY_REDEEM_NOTIFICATION, date_from, today, limit=50
            )
        except Exception as e:
            log.warning("redeem_notifications: list failed (%s)", e)
            await update_checkpoint(
                session, "redeem_notifications", rows_processed=0,
                status="skipped", error=str(e)[:500],
            )
            return 0

        if not docs:
            await update_checkpoint(session, "redeem_notifications", rows_processed=0)
            return 0

        # Какие уже есть в БД (избегаем повторных скачиваний)
        existing = (
            await session.execute(
                select(WbRedeemNotification.service_name).where(
                    WbRedeemNotification.service_name.in_(
                        [d.get("serviceName") for d in docs if d.get("serviceName")]
                    )
                )
            )
        ).scalars().all()
        existing_set = set(existing)

        new_docs = [d for d in docs if d.get("serviceName") not in existing_set]
        log.info(
            "redeem_notifications: tenant=%s found=%d new=%d",
            tenant_id, len(docs), len(new_docs),
        )

        for doc in new_docs:
            sname = doc.get("serviceName")
            if not sname:
                continue
            try:
                zip_bytes = await download_document(wb, sname, extension="zip")
                parsed = parse_redeem_notification(zip_bytes)
            except Exception as e:
                log.warning("redeem_notifications: %s failed (%s)", sname, e)
                continue

            stmt = pg_insert(WbRedeemNotification).values(
                tenant_id=tenant_id,
                notification_number=parsed["notification_number"],
                notification_date=parsed["notification_date"],
                total_sum_with_vat=parsed["total_sum_with_vat"],
                items=parsed["items"],
                service_name=parsed["service_name"],
            )
            # NB: `stmt.excluded.items` коллизит с dict.items() — SQLAlchemy
            # отдаёт bound method. Берём через subscript ['items'].
            stmt = stmt.on_conflict_do_update(
                index_elements=["tenant_id", "notification_number"],
                set_={
                    "notification_date": stmt.excluded["notification_date"],
                    "total_sum_with_vat": stmt.excluded["total_sum_with_vat"],
                    "items": stmt.excluded["items"],
                    "service_name": stmt.excluded["service_name"],
                },
            )
            await session.execute(stmt)
            total_synced += 1

        await session.commit()
        await update_checkpoint(
            session, "redeem_notifications", rows_processed=total_synced,
        )
    return total_synced


@celery_app.task(name="app.sync.tasks.sync_redeem_notifications_for_tenant")
def sync_redeem_notifications_for_tenant(tenant_id: int, days_back: int = 400) -> int:
    return asyncio.run(_sync_redeem_notifications_async(tenant_id, days_back))


@celery_app.task(name="app.sync.tasks.sync_redeem_notifications")
def sync_redeem_notifications_dispatch() -> dict[str, Any]:
    """Beat dispatcher (раз в день): fanout по активным tenants."""
    return _fanout(sync_redeem_notifications_for_tenant)


# ---------------------------------------------------------------------------
# Offset acts (Акт взаимозачёта, Documents API: actprofit)
# ---------------------------------------------------------------------------


async def _sync_offset_acts_async(tenant_id: int, days_back: int = 400) -> int:
    """Аналогично _sync_redeem_notifications_async — но для actprofit.
    Дублирует структуру: list → download → parse → upsert. У клиента
    обычно мало или нет этих документов, но если появятся — попадут в
    `income_offset` налогового отчёта."""
    from app.db.models import WbOffsetAct
    from app.integrations.wb.documents import (
        CATEGORY_OFFSET_ACT,
        download_document,
        list_documents,
        parse_offset_act,
    )

    today = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=days_back)

    total_synced = 0
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("offset_acts: tenant %s no token, skip", tenant_id)
            return 0
        session, wb = ctx

        try:
            docs = await list_documents(
                wb, CATEGORY_OFFSET_ACT, date_from, today, limit=50
            )
        except Exception as e:
            log.warning("offset_acts: list failed (%s)", e)
            await update_checkpoint(
                session, "offset_acts", rows_processed=0,
                status="skipped", error=str(e)[:500],
            )
            return 0

        if not docs:
            await update_checkpoint(session, "offset_acts", rows_processed=0)
            return 0

        existing = (
            await session.execute(
                select(WbOffsetAct.service_name).where(
                    WbOffsetAct.service_name.in_(
                        [d.get("serviceName") for d in docs if d.get("serviceName")]
                    )
                )
            )
        ).scalars().all()
        existing_set = set(existing)

        new_docs = [d for d in docs if d.get("serviceName") not in existing_set]
        log.info("offset_acts: tenant=%s found=%d new=%d", tenant_id, len(docs), len(new_docs))

        for doc in new_docs:
            sname = doc.get("serviceName")
            if not sname:
                continue
            try:
                zip_bytes = await download_document(wb, sname, extension="zip")
                parsed = parse_offset_act(zip_bytes)
            except Exception as e:
                log.warning("offset_acts: %s failed (%s)", sname, e)
                continue

            stmt = pg_insert(WbOffsetAct).values(
                tenant_id=tenant_id,
                act_number=parsed["act_number"],
                act_date=parsed["act_date"],
                total_sum=parsed["total_sum"],
                items=parsed["items"],
                service_name=parsed["service_name"],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["tenant_id", "act_number"],
                set_={
                    "act_date": stmt.excluded["act_date"],
                    "total_sum": stmt.excluded["total_sum"],
                    "items": stmt.excluded["items"],
                    "service_name": stmt.excluded["service_name"],
                },
            )
            await session.execute(stmt)
            total_synced += 1

        await session.commit()
        await update_checkpoint(session, "offset_acts", rows_processed=total_synced)
    return total_synced


@celery_app.task(name="app.sync.tasks.sync_offset_acts_for_tenant")
def sync_offset_acts_for_tenant(tenant_id: int, days_back: int = 400) -> int:
    return asyncio.run(_sync_offset_acts_async(tenant_id, days_back))


@celery_app.task(name="app.sync.tasks.sync_offset_acts")
def sync_offset_acts_dispatch() -> dict[str, Any]:
    """Beat dispatcher (раз в день): fanout по активным tenants."""
    return _fanout(sync_offset_acts_for_tenant)


# ─── Чарджбэки / штрафы (LEAD-005) ──────────────────────────────────────


async def _sync_chargebacks_async(tenant_id: int, lookback_days: int = 60) -> int:
    """Сканирует wb_report_detail за последние N дней и создаёт chargebacks
    для проблемных supplier_oper_name. Без вызовов WB API — чистый SQL UPSERT.
    Идемпотентен по UNIQUE(rrd_id, category).
    """
    from app.db.session import task_session_scope  # noqa: WPS433
    from app.services.chargebacks import sync_chargebacks as _do  # noqa: WPS433
    from app.services.tenant_context import set_tenant  # noqa: WPS433

    async with task_session_scope() as session:
        set_tenant(session, tenant_id)
        result = await _do(
            session, tenant_id=tenant_id, lookback_days=lookback_days
        )
        await update_checkpoint(
            session,
            "chargebacks",
            rows_processed=result["created"] + result["auto_closed"],
            status="ok",
        )
        return result["created"] + result["auto_closed"]


@celery_app.task(name="app.sync.tasks.sync_chargebacks_for_tenant")
def sync_chargebacks_for_tenant(tenant_id: int, lookback_days: int = 60) -> int:
    return asyncio.run(_sync_chargebacks_async(tenant_id, lookback_days))


@celery_app.task(name="app.sync.tasks.sync_chargebacks")
def sync_chargebacks_dispatch() -> dict[str, Any]:
    """Beat dispatcher: fanout по активным tenants (раз в день в 04:45 МСК)."""
    return _fanout(sync_chargebacks_for_tenant)


# ─── Перераспределение остатков (LEAD-008) ──────────────────────────────


async def _generate_redistribution_recs_async(tenant_id: int) -> int:
    """Daily генерация рекомендаций перераспределения.

    Грузит список активных nm_id из products (с продажами в последние 30 дней),
    через WB LK shifts API запрашивает остатки → собирает рекомендации →
    upsert в `redistribution_recommendations` со status='pending'.

    Если у tenant'а нет WbLkSession (или needs_relogin) — возвращает 0 и
    пропускает; никаких ошибок.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.models import (
        Product,
        RedistributionRecommendation,
        WbSale,
    )
    from app.db.session import task_session_scope
    from app.services.redistribution.recommender import build_recommendations
    from app.services.tenant_context import set_tenant

    async with task_session_scope() as session:
        set_tenant(session, tenant_id)

        # Активные SKU за 30 дней — только те у кого был хоть один Sale
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (
            await session.execute(
                select(Product.nm_id)
                .join(WbSale, WbSale.nm_id == Product.nm_id)
                .where(WbSale.sale_dt >= since)
                .where(WbSale.is_return.is_(False))
                .where(Product.is_archived.is_(False))
                .group_by(Product.nm_id)
                .limit(200)  # safety cap
            )
        ).all()
        nm_ids = [int(r[0]) for r in rows]
        if not nm_ids:
            await update_checkpoint(
                session, "redistribution_recs", rows_processed=0, status="ok"
            )
            return 0

        recs = await build_recommendations(
            session, tenant_id=tenant_id, nm_ids=nm_ids
        )
        if not recs:
            await update_checkpoint(
                session, "redistribution_recs", rows_processed=0, status="ok"
            )
            return 0

        # Прежние pending — пометить obsolete (status='dismissed'), новые insert.
        # Approved / queued / executed — не трогаем (это уже в работе).
        from sqlalchemy import update

        await session.execute(
            update(RedistributionRecommendation)
            .where(
                RedistributionRecommendation.tenant_id == tenant_id,
                RedistributionRecommendation.status == "pending",
            )
            .values(status="dismissed")
        )

        for r in recs:
            session.add(
                RedistributionRecommendation(
                    tenant_id=tenant_id,
                    nm_id=r.nm_id,
                    chrt_id=r.chrt_id,
                    from_office_id=r.from_office_id or None,
                    from_office_name=r.from_office_name,
                    to_office_id=r.to_office_id or None,
                    to_office_name=r.to_office_name,
                    qty=r.qty,
                    expected_logistics_saving_rub=r.econ.expected_logistics_saving_rub,
                    expected_revenue_uplift_rub=r.econ.expected_revenue_uplift_rub,
                    cost_share_rub=r.econ.cost_share_rub,
                    net_benefit_rub=r.econ.net_benefit_rub,
                    payback_days=r.econ.payback_days,
                    demand_14d_at_target=r.demand_14d_at_target,
                    current_stock_at_target=r.current_stock_at_target,
                    current_stock_at_source=r.current_stock_at_source,
                    transit_days_estimated=r.transit_days_estimated,
                    status="pending",
                )
            )

        await update_checkpoint(
            session, "redistribution_recs", rows_processed=len(recs), status="ok"
        )
        return len(recs)


@celery_app.task(name="app.sync.tasks.generate_redistribution_recs_for_tenant")
def generate_redistribution_recs_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_generate_redistribution_recs_async(tenant_id))


@celery_app.task(name="app.sync.tasks.generate_redistribution_recs")
def generate_redistribution_recs_dispatch() -> dict[str, Any]:
    """Beat dispatcher: daily в 06:00 МСК — fanout по tenants."""
    return _fanout(generate_redistribution_recs_for_tenant)


async def _publish_redistribution_windows_async() -> int:
    """Beat task — раз в минуту проверяет окно 09:00/18:00 МСК и публикует
    `redistribution.window.open` для активных tenants. Идемпотентно через
    consumer-side dedup (event_id с timestamp).
    """
    from app.db.session import task_session_scope
    from app.services.redistribution.scheduler import publish_window_event

    async with task_session_scope() as session:
        return await publish_window_event(session)


@celery_app.task(name="app.sync.tasks.publish_redistribution_windows")
def publish_redistribution_windows() -> int:
    return asyncio.run(_publish_redistribution_windows_async())


# ─── LEAD-016: execute_window — отправка queued tasks в WB LK ──────────


async def _execute_window_async(tenant_id: int) -> dict[str, Any]:
    """Per-tenant: читает queued redistribution_tasks, группирует и шлёт
    в WB через extension jobs queue (op='create_order'). См. execute_window.py.
    """
    from datetime import datetime, timezone

    from app.db.session import task_session_scope
    from app.services.redistribution.execute_window import (
        execute_window_for_tenant,
    )
    from app.services.tenant_context import set_tenant

    async with task_session_scope() as session:
        set_tenant(session, tenant_id)
        return await execute_window_for_tenant(
            session,
            tenant_id=tenant_id,
            window_dt=datetime.now(timezone.utc),
        )


@celery_app.task(name="app.sync.tasks.execute_window_for_tenant")
def execute_window_for_tenant_task(tenant_id: int) -> dict[str, Any]:
    """Celery wrapper для execute_window. Вызывается consumer'ом
    `consume_redistribution_window` для каждого активного tenant'а после
    получения события `redistribution.window.open`.
    """
    return asyncio.run(_execute_window_async(tenant_id))


# ─── LEAD-022: continuous polling вместо окон 09/18 ────────────────────
# Smoke 2026-05-20 показал что концепция «окон 09/18 МСК» неверна — WB
# открывает dst-квоты непрерывно (Электросталь = 19350+ единиц в 08:47 МСК),
# зато src-квоты гуляют (Волгоград закрыт для одного chrt_id, Краснодар
# открыт). Поэтому смысл polling'а в том чтобы:
#   1. постоянно (каждые 2 мин) проверять есть ли queued tasks у любого tenant'а
#   2. если есть — дёргать execute_window: он проверит dst quota,
#      попробует create_order. Если quota=0 на dst или WB отказала по
#      бизнес-причине (exceeded src quota) — task остаётся queued и
#      попробуется через 2 мин снова.
# Cooldown 72ч защищает от повторного create_order для (chrt, dst).


async def _try_execute_queued_tasks_async() -> dict[str, Any]:
    """Найти tenant'ов с queued tasks и попытаться отправить через
    execute_window. Используется как непрерывный poller взамен 09/18 окон.
    """
    from sqlalchemy import distinct, select

    from app.db.models import RedistributionTask
    from app.db.session import task_session_scope

    async with task_session_scope() as session:
        rows = (
            await session.execute(
                select(distinct(RedistributionTask.tenant_id)).where(
                    RedistributionTask.status == "queued"
                )
            )
        ).all()
    tenant_ids = [int(r[0]) for r in rows]
    if not tenant_ids:
        return {"tenants": 0, "dispatched": 0}

    # Async-dispatch — кладём задачи в Celery, не ждём результат
    for tid in tenant_ids:
        execute_window_for_tenant_task.delay(tid)
    log.info(
        "try_execute_queued: dispatched execute_window for %d tenant(s) with queued tasks",
        len(tenant_ids),
    )
    return {"tenants": len(tenant_ids), "dispatched": len(tenant_ids)}


@celery_app.task(name="app.sync.tasks.try_execute_queued_redistribution_tasks")
def try_execute_queued_redistribution_tasks() -> dict[str, Any]:
    """Beat-task каждые 2 мин: если есть queued redistribution_tasks у
    любого tenant'а — диспатчит execute_window. Замена для устаревшей
    концепции окон 09/18 МСК (LEAD-022).

    Cheap when idle: 1 SQL SELECT → возвращает {tenants:0, dispatched:0}.
    """
    return asyncio.run(_try_execute_queued_tasks_async())


# ─── Weekly digest для head_of_sales (LEAD-012) ─────────────────────────


@celery_app.task(name="app.sync.tasks.send_weekly_digest")
def send_weekly_digest() -> dict[str, Any]:
    """Beat-task: понедельник 10:00 МСК (07:00 UTC). Дайджест по всем
    активным tenant'ам у которых привязан tg_chat_id.
    """
    from app.services.digest_weekly import send_weekly_digests_all_tenants

    return asyncio.run(send_weekly_digests_all_tenants())


# ---------------------------------------------------------------------------
# Advertising
# ---------------------------------------------------------------------------


async def _sync_ad_campaigns_async(tenant_id: int) -> int:
    """Refresh campaign list (IDs + status/type/changeTime) via `/promotion/count`.

    This task makes EXACTLY ONE call to advert-api. Detailed metadata
    (name/dailyBudget/dates/paymentType) is fetched by a SEPARATE task
    `sync_ad_campaign_details` — chaining count + adverts in the same task
    triggers WB's burst-protection (penalty up to ~50 min) regardless of
    inter-call delay. See WB_API_REFERENCE.md §10 P-X (advert burst).
    """
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("ad_campaigns: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        try:
            overview = await fetch_campaigns_overview(wb)
        except Exception as e:
            log.warning("ad_campaigns: fetch failed (%s) — пропускаем синк", e)
            await update_checkpoint(
                session, "ad_campaigns", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
        if not overview:
            await update_checkpoint(session, "ad_campaigns", rows_processed=0)
            return 0

        # Upsert by advert_id. Only fields that come from /count are written;
        # name/daily_budget/start_time/end_time stay untouched if the row
        # already exists (they're owned by sync_ad_campaign_details).
        values = [
            {
                "advert_id": int(c["advertId"]),
                "type": c.get("type"),
                "status": c.get("status"),
                "change_time": _parse_dt(c.get("changeTime")),
            }
            for c in overview
        ]
        # Custom upsert: do NOT overwrite name/daily_budget/start_time/end_time
        # on conflict — those are filled by sync_ad_campaign_details and we
        # don't want /count to wipe them back to NULL.
        _stamp_tenant(session, WbAdCampaign, values)
        for start in range(0, len(values), 1000):
            chunk = values[start : start + 1000]
            stmt = pg_insert(WbAdCampaign).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["advert_id"],
                set_={
                    "type": stmt.excluded.type,
                    "status": stmt.excluded.status,
                    "change_time": stmt.excluded.change_time,
                },
            )
            await session.execute(stmt)

        await update_checkpoint(session, "ad_campaigns", rows_processed=len(values))
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_ad_campaigns_for_tenant")
def sync_ad_campaigns_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_ad_campaigns_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_ad_campaigns")
def sync_ad_campaigns_dispatch() -> dict[str, Any]:
    return _fanout(sync_ad_campaigns_for_tenant)




# ---------------------------------------------------------------------------
# Campaign details — separate from sync_ad_campaigns to avoid burst penalty.
# Runs less frequently and only for campaigns missing details (name IS NULL)
# or whose changeTime has moved since the last details fetch.
# ---------------------------------------------------------------------------


async def _sync_ad_campaign_details_async(tenant_id: int, limit: int = 50) -> int:
    """Fill in name/daily_budget/start_time/end_time for campaigns lacking them.

    Picks up to `limit` campaign IDs whose `name IS NULL` (= /adverts was never
    successfully called for them) and fetches via `/api/advert/v2/adverts`.
    `limit` defaults to 50 = exactly one chunk = exactly one WB call.
    """
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("ad_campaign_details: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        rows = (
            await session.execute(
                select(WbAdCampaign.advert_id)
                .where(WbAdCampaign.name.is_(None))
                .order_by(WbAdCampaign.advert_id)
                .limit(limit)
            )
        ).scalars().all()
        ids = [int(i) for i in rows]
        if not ids:
            await update_checkpoint(session, "ad_campaign_details", rows_processed=0)
            return 0
        try:
            info = await fetch_campaigns_info(wb, ids)
        except Exception as e:
            log.warning("ad_campaign_details: fetch failed (%s)", e)
            await update_checkpoint(
                session, "ad_campaign_details", rows_processed=0,
                status="skipped", error=str(e)[:500],
            )
            return 0
        if not info:
            await update_checkpoint(
                session, "ad_campaign_details", rows_processed=0,
                status="skipped", error="empty info response",
            )
            return 0

        updated = 0
        for c in info:
            adv_id = c.get("advertId")
            if adv_id is None:
                continue
            existing = await session.get(WbAdCampaign, int(adv_id))
            if not existing:
                continue
            existing.name = c.get("name")
            existing.daily_budget = c.get("dailyBudget")
            existing.start_time = _parse_dt(c.get("startTime"))
            existing.end_time = _parse_dt(c.get("endTime"))
            updated += 1
        await update_checkpoint(session, "ad_campaign_details", rows_processed=updated)
        return updated


@celery_app.task(name="app.sync.tasks.sync_ad_campaign_details_for_tenant")
def sync_ad_campaign_details_for_tenant(tenant_id: int, limit: int = 50) -> int:
    return asyncio.run(_sync_ad_campaign_details_async(tenant_id, limit))


@celery_app.task(name="app.sync.tasks.sync_ad_campaign_details")
def sync_ad_campaign_details_dispatch() -> dict[str, Any]:
    return _fanout(sync_ad_campaign_details_for_tenant)


async def _sync_ad_stats_async(tenant_id: int, days_back: int = 60) -> int:
    end = date.today()
    start = end - timedelta(days=days_back)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("ad_stats: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        # Read advert ids from local DB; sync_ad_campaigns refreshes them hourly.
        rows = (
            await session.execute(
                select(WbAdCampaign.advert_id, WbAdCampaign.status)
            )
        ).all()
        ids = [int(r[0]) for r in rows]
        if not ids:
            log.info("ad_stats: no campaigns in DB yet — run sync_ad_campaigns first")
            await update_checkpoint(session, "ad_stats", rows_processed=0)
            return 0
        # WB status codes: 9 = в работе. Если ни одной активной — fullstats для
        # paused/ended кампаний возвращает только исторические `days[]` до даты
        # остановки. Логируем явно, чтобы «дыра в синке» не казалась багом.
        active_cnt = sum(1 for r in rows if r[1] == 9)
        if active_cnt == 0:
            log.warning(
                "ad_stats: no active campaigns (status=9) among %d — "
                "fullstats will only return historical data up to last pause date",
                len(ids),
            )
        try:
            stats = await fetch_fullstats(wb, ids, date_from=start, date_to=end)
        except Exception as e:
            log.warning("ad_stats: fullstats failed (%s) — пропускаем", e)
            await update_checkpoint(
                session, "ad_stats", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0

        # Диагностика: сколько кампаний вернули непустой days[]. ROADMAP P1 —
        # «9 active кампаний без stats». WB иногда фильтрует на своей стороне
        # для status=7 (завершённых) или для очень старых периодов. Логируем
        # split: returned_with_data / total_requested. Если разрыв постоянен,
        # это WB-side ограничение, фикс не в нашем коде.
        with_data = sum(1 for c in stats if c.get("days"))
        if with_data < len(ids):
            ids_returned = {int(c.get("advertId", 0)) for c in stats if c.get("days")}
            missing = sorted(set(ids) - ids_returned)
            status_by_id = {int(r[0]): r[1] for r in rows}
            missing_by_status: dict[int, int] = {}
            for m in missing:
                st = status_by_id.get(m)
                missing_by_status[st] = missing_by_status.get(st, 0) + 1
            log.info(
                "ad_stats: %d/%d campaigns returned data; missing by status: %s",
                with_data, len(ids), dict(missing_by_status),
            )
        values: list[dict[str, Any]] = []
        for camp in stats:
            advert_id = camp.get("advertId")
            if advert_id is None:
                continue
            for day in camp.get("days", []) or []:
                stat_date = _parse_date(day.get("date"))
                if not stat_date:
                    continue
                # `apps` — platform breakdowns; per-product list is `nms` (v3,
                # since 2025-10) or `nm` (legacy v2 — kept as fallback so old
                # rows in cached JSON still parse).
                for app_block in day.get("apps", []) or []:
                    nm_blocks = (
                        app_block.get("nms")
                        or app_block.get("nm")
                        or []
                    )
                    if not nm_blocks:
                        # No per-product breakdown — store aggregate app-level row
                        values.append(
                            {
                                "advert_id": int(advert_id),
                                "stat_date": stat_date,
                                "nm_id": None,
                                "views": int(app_block.get("views") or 0),
                                "clicks": int(app_block.get("clicks") or 0),
                                "ctr": app_block.get("ctr") or 0,
                                "cpc": app_block.get("cpc") or 0,
                                # WB response field is `sum`, we store as sum_spent
                                "sum_spent": app_block.get("sum") or 0,
                                "atbs": int(app_block.get("atbs") or 0),
                                "orders": int(app_block.get("orders") or 0),
                                "cr": app_block.get("cr") or 0,
                                "shks": int(app_block.get("shks") or 0),
                                "sum_price": app_block.get("sum_price") or 0,
                            }
                        )
                    for nm in nm_blocks:
                        # nmId field in nm object (not "nm" as key)
                        raw_nm_id = nm.get("nmId") or nm.get("nmid") or nm.get("nm_id")
                        values.append(
                            {
                                "advert_id": int(advert_id),
                                "stat_date": stat_date,
                                "nm_id": int(raw_nm_id) if raw_nm_id else None,
                                "views": int(nm.get("views") or 0),
                                "clicks": int(nm.get("clicks") or 0),
                                "ctr": nm.get("ctr") or 0,
                                "cpc": nm.get("cpc") or 0,
                                # WB response field is `sum`, we store as sum_spent
                                "sum_spent": nm.get("sum") or 0,
                                "atbs": int(nm.get("atbs") or 0),
                                "orders": int(nm.get("orders") or 0),
                                "cr": nm.get("cr") or 0,
                                "shks": int(nm.get("shks") or 0),
                                "sum_price": nm.get("sum_price") or 0,
                            }
                        )

        # WB v3 fullstats can emit the same (advert_id, stat_date, nm_id) tuple
        # in multiple `apps[]` blocks (e.g. same product on site + Android +
        # iOS). The DB has a UNIQUE index `uq_ad_stats_advert_date_nm` on those
        # three columns — naive bulk-insert blows up with UniqueViolation and
        # rolls back the whole batch. Aggregate platform breakdowns into a
        # single per-product row before insert.
        agg: dict[tuple[int, date, int | None], dict[str, Any]] = {}
        for v in values:
            key = (v["advert_id"], v["stat_date"], v["nm_id"])
            cur = agg.get(key)
            if cur is None:
                agg[key] = dict(v)
                continue
            # Sum the count-like fields across platforms; for ratio fields
            # (ctr/cpc/cr) take the volume-weighted-ish average via re-derivation
            # after summing. For simplicity, prefer the latest non-zero value
            # — these are usually identical across same-day platform splits.
            for f in ("views", "clicks", "atbs", "orders", "shks"):
                cur[f] = int(cur.get(f, 0)) + int(v.get(f, 0))
            for f in ("sum_spent", "sum_price"):
                cur[f] = float(cur.get(f, 0) or 0) + float(v.get(f, 0) or 0)
            for f in ("ctr", "cpc", "cr"):
                if not cur.get(f) and v.get(f):
                    cur[f] = v[f]
        deduped = list(agg.values())
        if len(deduped) != len(values):
            log.info(
                "ad_stats: aggregated %d raw rows → %d unique (advert_id,date,nm_id)",
                len(values), len(deduped),
            )
        values = deduped

        if values:
            # Replace rows ТОЛЬКО за даты, которые реально перезагрузили. Раньше
            # удаляли весь [start, end] и вставляли успешные чанки — при WB 429 на
            # свежем чанке его данные стирались навсегда (регрессия данных рекламы).
            # Теперь удаляем только fetched-даты → даты упавшего чанка сохраняют
            # прежние данные. (TASK-DEV-056)
            fetched_dates = sorted({v["stat_date"] for v in values})
            try:
                await session.execute(
                    delete(WbAdStatsDaily).where(
                        WbAdStatsDaily.stat_date.in_(fetched_dates),
                    )
                )
                await _bulk_insert(session, WbAdStatsDaily, values)
                await update_checkpoint(session, "ad_stats", rows_processed=len(values))
            except Exception as e:
                # Roll back so the *checkpoint* update can succeed in a fresh
                # transaction. Without rollback, asyncpg raises
                # InFailedSQLTransactionError on the next INSERT and the real
                # cause is hidden — the user sees stale «WB cooldown» messages.
                log.error("ad_stats: insert failed (%s) — rolling back", e)
                try:
                    await session.rollback()
                except Exception:
                    pass
                try:
                    await update_checkpoint(
                        session, "ad_stats",
                        rows_processed=0,
                        status="failed",
                        error=f"{type(e).__name__}: {str(e)[:400]}",
                    )
                except Exception as ce:
                    log.error("ad_stats: checkpoint write also failed: %s", ce)
                return 0
        else:
            await update_checkpoint(
                session,
                "ad_stats",
                rows_processed=0,
                status="skipped",
                error="no fullstats data returned (WB cooldown or empty range)",
            )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_ad_stats_for_tenant")
def sync_ad_stats_for_tenant(tenant_id: int, days_back: int = 60) -> int:
    return asyncio.run(_sync_ad_stats_async(tenant_id, days_back))


@celery_app.task(name="app.sync.tasks.sync_ad_stats")
def sync_ad_stats() -> dict[str, Any]:
    return _fanout(sync_ad_stats_for_tenant)


# ---------------------------------------------------------------------------
# All-in-one bootstrap (used on first run)
# ---------------------------------------------------------------------------


async def _send_daily_digest_async() -> bool:
    """Send daily digest to the linked Telegram chat. No-op if not configured."""
    from sqlalchemy import select as _select  # local to avoid cycle confusion

    from app.bot.digest import build_daily_digest
    from app.core.config import settings as _cfg
    from app.db.models import AppSetting
    from app.integrations.telegram import send_message
    from app.services.tenant_context import set_tenant

    async with session_scope() as session:
        set_tenant(session, _cfg.bot_tenant_id)
        chat_id_row = (
            await session.execute(
                _select(AppSetting).where(
                    AppSetting.tenant_id == _cfg.bot_tenant_id,
                    AppSetting.key == "tg_chat_id",
                )
            )
        ).scalar_one_or_none()
        digest_enabled_row = (
            await session.execute(
                _select(AppSetting).where(
                    AppSetting.tenant_id == _cfg.bot_tenant_id,
                    AppSetting.key == "tg_digest_enabled",
                )
            )
        ).scalar_one_or_none()

    if not chat_id_row or not chat_id_row.value:
        log.info("daily_digest: tg_chat_id not set — skip")
        return False
    if digest_enabled_row and digest_enabled_row.value == "0":
        log.info("daily_digest: explicitly disabled — skip")
        return False

    text = await build_daily_digest()
    return await send_message(int(chat_id_row.value), text)


@celery_app.task(name="app.sync.tasks.send_daily_digest")
def send_daily_digest() -> bool:
    return asyncio.run(_send_daily_digest_async())


async def _evaluate_notifications_async() -> int:
    """Прогоняет все active rules для каждого tenant. Возвращает количество
    сработавших правил."""
    from app.db.session import task_session_scope
    from app.services.notification_engine import evaluate_all_rules
    from app.services.tenant_context import set_tenant
    total_fired = 0
    tenant_ids = await _list_active_tenants()
    for tid in tenant_ids:
        async with task_session_scope() as session:
            set_tenant(session, tid)
            try:
                evaluations = await evaluate_all_rules(session, dry_run=False)
                total_fired += sum(1 for e in evaluations if e.triggered)
            except Exception as e:
                log.warning("notifications: tenant %s failed: %s", tid, e)
    return total_fired


@celery_app.task(name="app.sync.tasks.evaluate_notifications")
def evaluate_notifications() -> int:
    """Celery beat: проверка active rules + отправка уведомлений в TG."""
    return asyncio.run(_evaluate_notifications_async())


async def _sync_product_photos_async(tenant_id: int) -> int:
    """Заполняет `products.photo_url` через WB Content API (раз в сутки).

    Без этого photo-proxy (`/api/products/{nm_id}/photo`) для каждого cold-MISS
    перебирает 12+ basket-CDN'ов до 200 OK (~700мс). С photo_url из БД —
    1 запрос, ~100мс.

    Идемпотентна: повторный запуск перезаписывает photo_url если поменялся
    (WB иногда меняет — переезд CDN, новый фото-сет)."""
    from app.integrations.wb.content import extract_photo_url, fetch_cards_list

    updated = 0
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("photos: tenant %s no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        try:
            async for batch in fetch_cards_list(wb, limit=100):
                # Готовим mapping nm_id → photo_url
                nm_to_url: dict[int, str] = {}
                for card in batch:
                    nm = card.get("nmID") or card.get("nmId")
                    if not nm:
                        continue
                    url = extract_photo_url(card)
                    if url:
                        nm_to_url[int(nm)] = url
                if not nm_to_url:
                    continue
                # UPDATE существующих Product записей (без insert: фото имеет
                # смысл только для уже синканных через orders/sales SKU).
                rows = (
                    await session.execute(
                        select(Product).where(Product.nm_id.in_(list(nm_to_url.keys())))
                    )
                ).scalars().all()
                for p in rows:
                    new_url = nm_to_url.get(p.nm_id)
                    if new_url and p.photo_url != new_url:
                        p.photo_url = new_url
                        updated += 1
                await session.commit()
        except Exception as e:
            log.warning("photos: fetch failed (%s) — skipping this run", e)
            return updated
    log.info("photos: tenant=%s updated=%d", tenant_id, updated)
    return updated


@celery_app.task(name="app.sync.tasks.sync_product_photos_for_tenant")
def sync_product_photos_for_tenant(tenant_id: int) -> int:
    return asyncio.run(_sync_product_photos_async(tenant_id))


@celery_app.task(name="app.sync.tasks.sync_product_photos")
def sync_product_photos() -> dict[str, Any]:
    return _fanout(sync_product_photos_for_tenant)


# ---------------------------------------------------------------------------
# WB Jam — поисковые запросы по карточкам (платная подписка)
# ---------------------------------------------------------------------------


async def _sync_jam_async(tenant_id: int, days_back: int = 30) -> dict[str, Any]:
    """Подтянуть ТОП-30 запросов из WB Jam для всех активных SKU тенанта.

    Endpoint берётся из tenant_settings (`wb_jam_url_template`); если пустой —
    пробует список дефолтных кандидатов (см. integrations/wb/jam.py).

    Возвращает {tenants_processed, skus_processed, queries_upserted, errors}.
    """
    from datetime import date as _date, timedelta as _td
    from app.db.models import AppSetting, JamQuery, Product
    from app.integrations.wb.jam import EndpointNotFoundError, fetch_jam_for_nm, normalize_jam_row
    from app.services.jam import upsert_jam_query

    end_date = _date.today()
    start_date = end_date - _td(days=days_back)
    upserted = 0
    skus_processed = 0
    errors: list[str] = []

    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("jam: tenant %s no WB token, skip", tenant_id)
            return {"tenant_id": tenant_id, "skipped": True, "reason": "no_token"}
        session, wb = ctx

        # Кастомный URL из settings (опционально)
        custom_url_row = (
            await session.execute(
                select(AppSetting).where(AppSetting.key == "wb_jam_url")
            )
        ).scalar_one_or_none()
        custom_path = custom_url_row.value if custom_url_row and custom_url_row.value else None

        # Список SKU (только активные = не архивные)
        nm_rows = (
            await session.execute(
                select(Product.nm_id).where(Product.is_archived.is_(False))
            )
        ).all()
        nm_ids = [int(r[0]) for r in nm_rows]
        if not nm_ids:
            log.info("jam: tenant %s — no active SKUs", tenant_id)
            await update_checkpoint(session, "jam", rows_processed=0)
            return {"tenant_id": tenant_id, "skus": 0, "upserted": 0}

        # Fetch по одному SKU за раз, лимит analytics 3/мин — пройдёмся аккуратно.
        for nm in nm_ids:
            try:
                raw = await fetch_jam_for_nm(
                    wb,
                    nm_id=nm,
                    date_from=start_date,
                    date_to=end_date,
                    limit=30,
                    custom_path=custom_path,
                )
            except EndpointNotFoundError as e:
                # Все API-кандидаты 404. TASK-LEAD-142: WB перенёс поисковые
                # запросы в ЛК-внутренний API (seller-content), токен туда не
                # ходит. Данные теперь поступают через Chrome-extension
                # (POST /api/jam/upload-extension). Если в jam_queries уже есть
                # свежие данные от расширения — это НЕ ошибка, помечаем ok.
                jam_have = (await session.execute(
                    select(func.count(JamQuery.id)).where(
                        JamQuery.tenant_id == tenant_id
                    )
                )).scalar() or 0
                if jam_have > 0:
                    msg = None  # данные есть (через extension) — не шумим
                    log.info("jam: API 404, но %d запросов есть через extension", jam_have)
                else:
                    msg = (
                        "WB Jam через API недоступен (поисковые запросы в ЛК-"
                        "внутреннем API). Установите Chrome-расширение РНП и "
                        "откройте «Поисковые запросы» по карточкам в ЛК — данные "
                        "подтянутся автоматически в /jam."
                    )
                    errors.append(msg)
                log.info("jam: endpoint not found via API — %s", e)
                break
            except Exception as e:
                msg = f"nm {nm}: {type(e).__name__}: {str(e)[:200]}"
                errors.append(msg)
                log.warning("jam: %s", msg)
                # Если 401/403 — нет смысла продолжать всем SKU
                if "401" in str(e) or "403" in str(e):
                    log.error("jam: subscription/scope error — abort sync")
                    break
                continue
            skus_processed += 1
            for raw_row in raw:
                norm = normalize_jam_row(
                    raw_row, nm_id=nm, period_start=start_date, period_end=end_date
                )
                if not norm:
                    continue
                await upsert_jam_query(session, **norm)
                upserted += 1
            # Промежуточный commit для каждого SKU — чтобы прогресс сохранялся даже при сбое
            await session.commit()

        status = "ok" if not errors else ("skipped" if upserted == 0 else "partial")
        await update_checkpoint(
            session,
            "jam",
            rows_processed=upserted,
            status=status,
            error="; ".join(errors[:3])[:500] if errors else None,
        )

    return {
        "tenant_id": tenant_id,
        "skus_processed": skus_processed,
        "queries_upserted": upserted,
        "errors": errors[:5],
    }


@celery_app.task(name="app.sync.tasks.sync_jam_for_tenant")
def sync_jam_for_tenant(tenant_id: int, days_back: int = 30) -> dict[str, Any]:
    return asyncio.run(_sync_jam_async(tenant_id, days_back))


@celery_app.task(name="app.sync.tasks.sync_jam")
def sync_jam() -> dict[str, Any]:
    return _fanout(sync_jam_for_tenant)


@celery_app.task(name="app.sync.tasks.sync_all")
def sync_all() -> dict[str, Any]:
    """Запустить все dispatcher'ы (fanout per-tenant для каждого синка)."""
    return {
        "orders": sync_orders(),
        "sales": sync_sales(),
        "stocks": sync_stocks(),
        "ad_campaigns": sync_ad_campaigns_dispatch(),
        "ad_campaign_details": sync_ad_campaign_details_dispatch(),
        "ad_stats": sync_ad_stats(),
        "report_detail": sync_report_detail_dispatch(),
        "paid_storage": sync_paid_storage(),
    }
