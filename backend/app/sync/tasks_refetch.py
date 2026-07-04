"""Переподгрузка исторических WB-отчётов с версионированием (TASK-DEV-095).

Отличие от обычных sync-тасков: перед записью свежие строки СРАВНИВАЮТСЯ с
сохранёнными через `services/wb_revision.diff_and_apply` — актуальные данные
попадают в основную таблицу, прежние значения и отклонённые (FREEZE)
обновления — в журнал `wb_sync_change`. Итог каждого прохода — запись
`wb_sync_revision` со счётчиками и сводной дельтой сумм.

Источники и их возможности (WB_API_REFERENCE.md § 3, § 9):
  report_detail — finance-api отдаёт ЛЮБОЙ период (rrd-курсор, 1 req/min).
  ad_stats      — fullstats до 31 дня за вызов, авто-чанки; волатилен у
                  throttled-продавца → FREEZE по sum_spent (Правило 3.5).
  orders/sales  — /supplier/orders|sales flag=0 (изменённые с dateFrom);
                  Base token: ≤1/3ч и ≤1/2ч соответственно → только weekly.
  funnel        — WB Analytics rolling-7 ЖЁСТКО: переподгрузка возможна
                  только внутри последних 7 дней, backfill невозможен.

Расписание — см. beat_schedule в celery_app.py (ночью, вразрез с обычными
sync'ами чтобы не топтать те же rate-limit категории).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select

from app.core.logging import get_logger
from app.db.models import (
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbFunnelDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
)
from app.integrations.wb.advert import fetch_fullstats
from app.integrations.wb.analytics import fetch_nm_report_history
from app.integrations.wb.statistics import (
    fetch_orders,
    fetch_report_detail_v2,
    fetch_sales,
)
from app.services.wb_revision import diff_and_apply
from app.sync.celery_app import celery_app
from app.sync.tasks import (
    _ensure_products,
    _fanout,
    _fullstats_values,
    _map_order_row,
    _map_report_detail_row,
    _map_sale_row,
)
from app.sync.tasks_funnel import (
    DATE_CHUNK_DAYS,
    NM_CHUNK,
    _date_chunks,
    _extract_history,
    _extract_nm_id,
)
from app.sync.tasks_funnel import _parse_dt as _parse_funnel_date
from app.sync.tenants import tenant_sync_context

log = get_logger(__name__)

# Какие поля сравниваем/журналируем per source. Не все 88 колонок
# report_detail — только влияющие на деньги/аналитику (шум типа office_name
# не журналим, но в основную таблицу upsert перезапишет всё).
REPORT_DETAIL_TRACKED = [
    "quantity", "retail_price", "retail_amount", "retail_price_withdisc_rub",
    "ppvz_for_pay", "delivery_rub", "storage_fee", "penalty", "deduction",
    "acquiring_fee", "additional_payment", "supplier_oper_name", "rr_dt",
]
AD_STATS_TRACKED = [
    "views", "clicks", "sum_spent", "atbs", "orders", "shks", "sum_price",
]
ORDERS_TRACKED = [
    "is_cancel", "cancel_dt", "total_price", "price_with_disc",
    "finished_price", "spp", "discount_percent", "warehouse_name",
]
SALES_TRACKED = [
    "for_pay", "total_price", "price_with_disc", "finished_price",
    "spp", "commission_percent", "is_return",
]
FUNNEL_TRACKED = [
    "orders_count", "buyouts_count", "orders_sum_rub",
    "open_count", "cart_count",
]


def _dedup_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Убрать дубли по PK (побеждает последняя строка). Refetch копит все
    чанки в один upsert — дубль внутри одного INSERT валит его целиком
    («ON CONFLICT DO UPDATE cannot affect row a second time»)."""
    seen: dict[Any, dict[str, Any]] = {}
    for r in rows:
        seen[r[key]] = r
    return list(seen.values())


# ---------------------------------------------------------------------------
# report_detail — finance-api умеет любой период
# ---------------------------------------------------------------------------


async def _refetch_report_detail_async(
    tenant_id: int, days_back: int = 42, triggered_by: str = "beat"
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            return {"status": "skipped", "reason": "no_token"}
        session, wb = ctx
        rows: list[dict[str, Any]] = []
        try:
            async for chunk in fetch_report_detail_v2(wb, date_from=start, date_to=end):
                await _ensure_products(session, chunk)
                for r in chunk:
                    v = _map_report_detail_row(r)
                    if v is not None:
                        rows.append(v)
        except Exception as e:
            log.warning("refetch.report_detail: tenant=%s fetch failed: %s", tenant_id, e)
            return {"status": "skipped", "reason": str(e)[:200]}
        rows = _dedup_by(rows, "rrd_id")
        result = await diff_and_apply(
            session,
            tenant_id=tenant_id,
            source="report_detail",
            period_from=start.date(),
            period_to=end.date(),
            model=WbReportDetail,
            new_rows=rows,
            key_fn=lambda r: f"rrd:{r['rrd_id']}",
            pk_cols=["rrd_id"],
            tracked_fields=REPORT_DETAIL_TRACKED,
            triggered_by=triggered_by,
        )
        return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# ad_stats — fullstats, FREEZE по sum_spent
# ---------------------------------------------------------------------------


async def _refetch_ad_stats_async(
    tenant_id: int, days_back: int = 30, triggered_by: str = "beat"
) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=days_back)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            return {"status": "skipped", "reason": "no_token"}
        session, wb = ctx
        ids = (
            (await session.execute(select(WbAdCampaign.advert_id))).scalars().all()
        )
        ids = [int(i) for i in ids]
        if not ids:
            return {"status": "skipped", "reason": "no_campaigns"}
        try:
            stats = await fetch_fullstats(wb, ids, date_from=start, date_to=end)
        except Exception as e:
            log.warning("refetch.ad_stats: tenant=%s fetch failed: %s", tenant_id, e)
            return {"status": "skipped", "reason": str(e)[:200]}
        values = _fullstats_values(stats)
        # Строки без nm-разбивки (nm_id=NULL): уникальный индекс Postgres не
        # матчит NULL в ON CONFLICT → upsert плодил бы дубли. Обычный sync
        # решает это DELETE+insert; в diff-режиме их просто пропускаем.
        skipped_null = sum(1 for v in values if v["nm_id"] is None)
        if skipped_null:
            log.info("refetch.ad_stats: %d app-level rows (nm_id=NULL) skipped", skipped_null)
        values = [v for v in values if v["nm_id"] is not None]
        result = await diff_and_apply(
            session,
            tenant_id=tenant_id,
            source="ad_stats",
            period_from=start,
            period_to=end,
            model=WbAdStatsDaily,
            new_rows=values,
            key_fn=lambda r: f"ad:{r['advert_id']}:{r['stat_date']}:{r['nm_id']}",
            pk_cols=["advert_id", "stat_date", "nm_id"],
            tracked_fields=AD_STATS_TRACKED,
            freeze_field="sum_spent",
            triggered_by=triggered_by,
            existing_filter=and_(
                WbAdStatsDaily.stat_date >= start,
                WbAdStatsDaily.stat_date <= end,
                WbAdStatsDaily.nm_id.isnot(None),
            ),
        )
        return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# orders / sales — statistics-api, flag=0 с dateFrom = start периода
# ---------------------------------------------------------------------------


async def _refetch_orders_async(
    tenant_id: int, days_back: int = 45, triggered_by: str = "beat"
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            return {"status": "skipped", "reason": "no_token"}
        session, wb = ctx
        try:
            raw = await fetch_orders(wb, date_from=start, flag=0)
        except Exception as e:
            log.warning("refetch.orders: tenant=%s fetch failed: %s", tenant_id, e)
            return {"status": "skipped", "reason": str(e)[:200]}
        await _ensure_products(session, raw)
        rows = _dedup_by(
            [v for v in (_map_order_row(r) for r in raw) if v is not None], "srid"
        )
        result = await diff_and_apply(
            session,
            tenant_id=tenant_id,
            source="orders",
            period_from=start.date(),
            period_to=end.date(),
            model=WbOrder,
            new_rows=rows,
            key_fn=lambda r: f"srid:{r['srid']}",
            pk_cols=["srid"],
            tracked_fields=ORDERS_TRACKED,
            triggered_by=triggered_by,
        )
        return {"status": "ok", **result}


async def _refetch_sales_async(
    tenant_id: int, days_back: int = 45, triggered_by: str = "beat"
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            return {"status": "skipped", "reason": "no_token"}
        session, wb = ctx
        try:
            raw = await fetch_sales(wb, date_from=start, flag=0)
        except Exception as e:
            log.warning("refetch.sales: tenant=%s fetch failed: %s", tenant_id, e)
            return {"status": "skipped", "reason": str(e)[:200]}
        await _ensure_products(session, raw)
        rows = _dedup_by(
            [v for v in (_map_sale_row(r) for r in raw) if v is not None], "sale_id"
        )
        result = await diff_and_apply(
            session,
            tenant_id=tenant_id,
            source="sales",
            period_from=start.date(),
            period_to=end.date(),
            model=WbSale,
            new_rows=rows,
            key_fn=lambda r: f"sale:{r['sale_id']}",
            pk_cols=["sale_id"],
            tracked_fields=SALES_TRACKED,
            triggered_by=triggered_by,
        )
        return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# funnel — только rolling-7 (WB-лимит), diff внутри окна
# ---------------------------------------------------------------------------


async def _refetch_funnel_async(
    tenant_id: int, days_back: int = 7, triggered_by: str = "beat"
) -> dict[str, Any]:
    days_back = min(days_back, 7)  # WB v3 sales-funnel: >7 дней → 400
    today = date.today()
    date_from = today - timedelta(days=days_back - 1)
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            return {"status": "skipped", "reason": "no_token"}
        session, wb = ctx
        nm_ids_raw = (
            (await session.execute(select(Product.nm_id))).scalars().all()
        )
        nm_ids = sorted({int(n) for n in nm_ids_raw if n})
        if not nm_ids:
            return {"status": "skipped", "reason": "no_nm_ids"}
        synced_at = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        try:
            for d_from, d_to in _date_chunks(date_from, today, DATE_CHUNK_DAYS):
                for i in range(0, len(nm_ids), NM_CHUNK):
                    cards = await fetch_nm_report_history(
                        wb, nm_ids=nm_ids[i:i + NM_CHUNK],
                        date_from=d_from, date_to=d_to,
                    )
                    for card in cards:
                        nm = _extract_nm_id(card)
                        if nm is None:
                            continue
                        for h in _extract_history(card):
                            dt = _parse_funnel_date(h.get("date") or h.get("dt"))
                            if dt is None:
                                continue
                            open_count = h.get("openCount") or h.get("openCardCount")
                            cart_count = h.get("cartCount") or h.get("addToCartCount")
                            rows.append({
                                "tenant_id": tenant_id,
                                "nm_id": nm,
                                "dt": dt,
                                "orders_count": int(h.get("orderCount") or h.get("ordersCount") or 0),
                                "buyouts_count": int(h.get("buyoutCount") or h.get("buyoutsCount") or 0),
                                "orders_sum_rub": float(h.get("orderSum") or h.get("ordersSumRub") or 0),
                                "open_count": int(open_count) if open_count else None,
                                "cart_count": int(cart_count) if cart_count else None,
                                "synced_at": synced_at,
                            })
        except Exception as e:
            log.warning("refetch.funnel: tenant=%s fetch failed: %s", tenant_id, e)
            return {"status": "skipped", "reason": str(e)[:200]}
        result = await diff_and_apply(
            session,
            tenant_id=tenant_id,
            source="funnel",
            period_from=date_from,
            period_to=today,
            model=WbFunnelDaily,
            new_rows=rows,
            key_fn=lambda r: f"funnel:{r['nm_id']}:{r['dt']}",
            pk_cols=["tenant_id", "nm_id", "dt"],
            tracked_fields=FUNNEL_TRACKED,
            triggered_by=triggered_by,
            existing_filter=WbFunnelDaily.dt >= date_from,
        )
        return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# Celery tasks: per-tenant + fanout-диспетчеры
# ---------------------------------------------------------------------------

_CORES = {
    "report_detail": _refetch_report_detail_async,
    "ad_stats": _refetch_ad_stats_async,
    "orders": _refetch_orders_async,
    "sales": _refetch_sales_async,
    "funnel": _refetch_funnel_async,
}


@celery_app.task(name="refetch.source_for_tenant")
def refetch_source_for_tenant(
    tenant_id: int, source: str, days_back: int, triggered_by: str = "manual"
) -> dict[str, Any]:
    """Единая точка ручного запуска (API /api/data-revisions/refetch)."""
    core = _CORES.get(source)
    if core is None:
        return {"status": "error", "reason": f"unknown source {source!r}"}
    return asyncio.run(core(tenant_id, days_back=days_back, triggered_by=triggered_by))


@celery_app.task(name="refetch.report_detail_for_tenant")
def refetch_report_detail_for_tenant(tenant_id: int, days_back: int = 42) -> dict[str, Any]:
    return asyncio.run(_refetch_report_detail_async(tenant_id, days_back=days_back))


@celery_app.task(name="refetch.report_detail")
def refetch_report_detail(days_back: int = 42) -> dict[str, Any]:
    return _fanout(refetch_report_detail_for_tenant, days_back)


@celery_app.task(name="refetch.ad_stats_for_tenant")
def refetch_ad_stats_for_tenant(tenant_id: int, days_back: int = 30) -> dict[str, Any]:
    return asyncio.run(_refetch_ad_stats_async(tenant_id, days_back=days_back))


@celery_app.task(name="refetch.ad_stats")
def refetch_ad_stats(days_back: int = 30) -> dict[str, Any]:
    return _fanout(refetch_ad_stats_for_tenant, days_back)


@celery_app.task(name="refetch.orders_for_tenant")
def refetch_orders_for_tenant(tenant_id: int, days_back: int = 45) -> dict[str, Any]:
    return asyncio.run(_refetch_orders_async(tenant_id, days_back=days_back))


@celery_app.task(name="refetch.orders")
def refetch_orders(days_back: int = 45) -> dict[str, Any]:
    return _fanout(refetch_orders_for_tenant, days_back)


@celery_app.task(name="refetch.sales_for_tenant")
def refetch_sales_for_tenant(tenant_id: int, days_back: int = 45) -> dict[str, Any]:
    return asyncio.run(_refetch_sales_async(tenant_id, days_back=days_back))


@celery_app.task(name="refetch.sales")
def refetch_sales(days_back: int = 45) -> dict[str, Any]:
    return _fanout(refetch_sales_for_tenant, days_back)


@celery_app.task(name="refetch.funnel_for_tenant")
def refetch_funnel_for_tenant(tenant_id: int, days_back: int = 7) -> dict[str, Any]:
    return asyncio.run(_refetch_funnel_async(tenant_id, days_back=days_back))


@celery_app.task(name="refetch.funnel")
def refetch_funnel(days_back: int = 7) -> dict[str, Any]:
    return _fanout(refetch_funnel_for_tenant, days_back)
