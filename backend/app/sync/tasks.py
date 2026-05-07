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
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbOrder,
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
from app.integrations.wb.statistics import (
    fetch_orders,
    fetch_report_detail,
    fetch_sales,
    fetch_stocks,
)
from app.sync.celery_app import celery_app
from app.sync.checkpoints import get_date_from, update_checkpoint

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
    for start in range(0, len(rows), _BULK_CHUNK_ROWS):
        chunk = rows[start : start + _BULK_CHUNK_ROWS]
        stmt = pg_insert(Product).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["nm_id"],
            set_={
                "vendor_code": stmt.excluded.vendor_code,
                "subject": stmt.excluded.subject,
                "brand": stmt.excluded.brand,
                "category": stmt.excluded.category,
                "last_seen_at": stmt.excluded.last_seen_at,
                "is_archived": stmt.excluded.is_archived,
            },
        )
        await session.execute(stmt)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def _sync_orders_async() -> int:
    async with session_scope() as session, WbApiClient() as wb:
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
                }
            )

        await _bulk_upsert(session, WbOrder, values, pk_cols=["srid"])

        await update_checkpoint(
            session, "orders", last_change_date=max_lcd, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_orders")
def sync_orders() -> int:
    return asyncio.run(_sync_orders_async())


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


async def _sync_sales_async() -> int:
    async with session_scope() as session, WbApiClient() as wb:
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
                }
            )

        await _bulk_upsert(session, WbSale, values, pk_cols=["sale_id"])

        await update_checkpoint(
            session, "sales", last_change_date=max_lcd, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_sales")
def sync_sales() -> int:
    return asyncio.run(_sync_sales_async())


# ---------------------------------------------------------------------------
# Stocks (full snapshot, written with current timestamp)
# ---------------------------------------------------------------------------


async def _sync_stocks_async() -> int:
    snapshot_dt = datetime.now(timezone.utc).replace(microsecond=0)
    async with session_scope() as session, WbApiClient() as wb:
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
                }
            )
        await _bulk_insert(session, WbStockSnapshot, values)

        await update_checkpoint(
            session, "stocks", last_change_date=snapshot_dt, rows_processed=len(values)
        )
        return len(values)


@celery_app.task(name="app.sync.tasks.sync_stocks")
def sync_stocks() -> int:
    return asyncio.run(_sync_stocks_async())


# ---------------------------------------------------------------------------
# Report Detail (source of truth for P&L)
# ---------------------------------------------------------------------------


async def _sync_report_detail_async(days_back: int = 14) -> int:
    """Re-pull report detail for the last `days_back` days (rows continue arriving)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    total = 0
    async with session_scope() as session, WbApiClient() as wb:
        try:
            chunks_iter = fetch_report_detail(wb, date_from=start, date_to=end)
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


@celery_app.task(name="app.sync.tasks.sync_report_detail")
def sync_report_detail(days_back: int = 14) -> int:
    return asyncio.run(_sync_report_detail_async(days_back=days_back))


# ---------------------------------------------------------------------------
# Advertising
# ---------------------------------------------------------------------------


async def _sync_ad_campaigns_async() -> int:
    """Refresh campaign list (IDs + status/type/changeTime) via `/promotion/count`.

    This task makes EXACTLY ONE call to advert-api. Detailed metadata
    (name/dailyBudget/dates/paymentType) is fetched by a SEPARATE task
    `sync_ad_campaign_details` — chaining count + adverts in the same task
    triggers WB's burst-protection (penalty up to ~50 min) regardless of
    inter-call delay. See WB_API_REFERENCE.md §10 P-X (advert burst).
    """
    async with session_scope() as session, WbApiClient() as wb:
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


@celery_app.task(name="app.sync.tasks.sync_ad_campaigns")
def sync_ad_campaigns() -> int:
    return asyncio.run(_sync_ad_campaigns_async())


# ---------------------------------------------------------------------------
# Campaign details — separate from sync_ad_campaigns to avoid burst penalty.
# Runs less frequently and only for campaigns missing details (name IS NULL)
# or whose changeTime has moved since the last details fetch.
# ---------------------------------------------------------------------------


async def _sync_ad_campaign_details_async(limit: int = 50) -> int:
    """Fill in name/daily_budget/start_time/end_time for campaigns lacking them.

    Picks up to `limit` campaign IDs whose `name IS NULL` (= /adverts was never
    successfully called for them) and fetches via `/api/advert/v2/adverts`.
    `limit` defaults to 50 = exactly one chunk = exactly one WB call.
    """
    async with session_scope() as session, WbApiClient() as wb:
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


@celery_app.task(name="app.sync.tasks.sync_ad_campaign_details")
def sync_ad_campaign_details(limit: int = 50) -> int:
    return asyncio.run(_sync_ad_campaign_details_async(limit=limit))


async def _sync_ad_stats_async(days_back: int = 30) -> int:
    end = date.today()
    start = end - timedelta(days=days_back)
    async with session_scope() as session, WbApiClient() as wb:
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


@celery_app.task(name="app.sync.tasks.sync_ad_stats")
def sync_ad_stats(days_back: int = 30) -> int:
    return asyncio.run(_sync_ad_stats_async(days_back=days_back))


# ---------------------------------------------------------------------------
# All-in-one bootstrap (used on first run)
# ---------------------------------------------------------------------------


async def _send_daily_digest_async() -> bool:
    """Send daily digest to the linked Telegram chat. No-op if not configured."""
    from sqlalchemy import select as _select  # local to avoid cycle confusion

    from app.bot.digest import build_daily_digest
    from app.db.models import AppSetting
    from app.integrations.telegram import send_message

    async with session_scope() as session:
        chat_id_row = (
            await session.execute(
                _select(AppSetting).where(AppSetting.key == "tg_chat_id")
            )
        ).scalar_one_or_none()
        digest_enabled_row = (
            await session.execute(
                _select(AppSetting).where(AppSetting.key == "tg_digest_enabled")
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
def sync_all() -> dict[str, int]:
    return {
        "orders": sync_orders(),
        "sales": sync_sales(),
        "stocks": sync_stocks(),
        "ad_campaigns": sync_ad_campaigns(),
        "ad_campaign_details": sync_ad_campaign_details(),
        "ad_stats": sync_ad_stats(),
        "report_detail": sync_report_detail(),
    }
