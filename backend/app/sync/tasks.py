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
    fetch_report_detail_v2,
    fetch_sales,
    fetch_stocks,
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


def _fanout(per_tenant_task) -> dict[str, Any]:
    """Запустить per-tenant task для каждого активного tenant'а."""
    tenants = asyncio.run(_list_active_tenants())
    if not tenants:
        log.info("dispatcher: no active tenants (no WB token set)")
        return {"tenants_scheduled": 0}
    for tid in tenants:
        per_tenant_task.delay(tid)
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


# asyncpg / Postgres binary protocol limit: max 32767 bind parameters per query.
# Pick a chunk size that keeps us well under that even for the widest table
# (report_detail at ~26 cols → 1000 × 26 = 26000 params, under the cap).
_BULK_CHUNK_ROWS = 1000


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
    for start in range(0, len(values), _BULK_CHUNK_ROWS):
        chunk = values[start : start + _BULK_CHUNK_ROWS]
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
    for start in range(0, len(values), _BULK_CHUNK_ROWS):
        chunk = values[start : start + _BULK_CHUNK_ROWS]
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
                            "rrd_id": int(rrd),
                            "realization_id": r.get("realizationreport_id"),
                            "report_date_from": _parse_date(r.get("date_from")),
                            "report_date_to": _parse_date(r.get("date_to")),
                            "create_dt": _parse_date(r.get("create_dt")),
                            "nm_id": int(r["nm_id"]) if r.get("nm_id") else None,
                            "sa_name": r.get("sa_name"),
                            "barcode": r.get("barcode"),
                            "doc_type_name": r.get("doc_type_name"),
                            "supplier_oper_name": r.get("supplier_oper_name"),
                            "order_dt": _parse_dt(r.get("order_dt")),
                            "sale_dt": _parse_dt(r.get("sale_dt")),
                            "rr_dt": _parse_date(r.get("rr_dt")),
                            "quantity": int(r.get("quantity") or 0),
                            "retail_price": r.get("retail_price") or 0,
                            "retail_amount": r.get("retail_amount") or 0,
                            "sale_percent": r.get("sale_percent") or 0,
                            "commission_percent": r.get("commission_percent") or 0,
                            "ppvz_for_pay": r.get("ppvz_for_pay") or 0,
                            "delivery_rub": r.get("delivery_rub") or 0,
                            "storage_fee": r.get("storage_fee") or 0,
                            "penalty": r.get("penalty") or 0,
                            "additional_payment": r.get("additional_payment") or 0,
                            "deduction": r.get("deduction") or 0,
                            "acquiring_fee": r.get("acquiring_fee") or 0,
                            # Fields added in WB API v5 (2025-2026)
                            "retail_price_withdisc_rub": r.get("retail_price_withdisc_rub"),
                            "kiz": r.get("kiz") or None,
                            # НДС-related (present for VAT payers from 2026)
                            "ppvz_vw": r.get("ppvz_vw"),
                            "ppvz_vw_nds": r.get("ppvz_vw_nds"),
                            "supplier_reward": r.get("supplier_reward"),
                        }
                    )
                await _bulk_upsert(session, WbReportDetail, values, pk_cols=["rrd_id"])
                total += len(values)
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
        ids_rows = (
            await session.execute(select(WbAdCampaign.advert_id))
        ).scalars().all()
        ids = [int(i) for i in ids_rows]
        if not ids:
            log.info("ad_stats: no campaigns in DB yet — run sync_ad_campaigns first")
            await update_checkpoint(session, "ad_stats", rows_processed=0)
            return 0
        try:
            stats = await fetch_fullstats(wb, ids, date_from=start, date_to=end)
        except Exception as e:
            log.warning("ad_stats: fullstats failed (%s) — пропускаем", e)
            await update_checkpoint(
                session, "ad_stats", rows_processed=0, status="skipped", error=str(e)[:500]
            )
            return 0
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
            # Replace rows in (advert_id, date) range to keep idempotency.
            # Only delete when we have new data — an empty values list means
            # every chunk was rejected (cooldown or WB error), and we don't
            # want to wipe yesterday's good data on today's failed sync.
            try:
                await session.execute(
                    delete(WbAdStatsDaily).where(
                        WbAdStatsDaily.stat_date >= start,
                        WbAdStatsDaily.stat_date <= end,
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
