"""Manual backfill of `wb_report_detail` for arbitrary historical periods.

The regular `sync_report_detail` Celery task pulls only the last 14 days, so
older history must be filled in via this one-off script. It walks the requested
date window once, paginates by `rrdId` cursor, and upserts to the same table —
fully idempotent (PK = rrd_id), safe to re-run on overlapping ranges.

**Endpoint:** new `POST /api/finance/v1/sales-reports/detailed` on finance-api.
This replaces the deprecated `/reportDetailByPeriod` (sunset 2026-07-15). The
new endpoint has a single 1/min limit for both Personal and Base tokens — no
2/24h cap — so backfilling N weeks now takes ~N minutes, not N days.

Usage::

    docker compose exec backend python -m scripts.backfill_report_detail \\
        --tenant 1 --from 2026-02-01 --to 2026-04-26

The script is tenant-aware: pass `--tenant <id>` (default 1). The script reads
the tenant's WB token from `tenants.wb_token` via `tenant_sync_context`.

If you saw a 429 from any statistics-category call recently, check
`redis-cli TTL wb:cooldown:finance` — though finance is its own category and
shouldn't be affected by statistics-side penalties.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone

from app.core.logging import configure_logging, get_logger
from app.db.models import WbReportDetail
from app.integrations.wb.statistics import fetch_report_detail_v2
from app.sync.tasks import _bulk_upsert, _ensure_products, _parse_date, _parse_dt
from app.sync.tenants import tenant_sync_context

log = get_logger(__name__)


async def backfill(
    tenant_id: int, date_from: date, date_to: date, dry_run: bool = False
) -> int:
    """Pull report_detail for [date_from, date_to] (inclusive) and upsert."""
    log.info(
        "backfill: tenant=%s %s..%s (dry_run=%s)",
        tenant_id, date_from, date_to, dry_run,
    )
    start_ts = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)

    total_rows = 0
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.error("backfill: tenant %s has no WB token, abort", tenant_id)
            return 0
        session, wb = ctx
        try:
            chunks_iter = fetch_report_detail_v2(wb, date_from=start_ts, date_to=end_ts)
        except Exception as e:
            log.error("backfill: WB call failed before pagination: %s", e)
            return 0

        chunk_no = 0
        try:
            async for chunk in chunks_iter:
                chunk_no += 1
                log.info("backfill: chunk %d, %d rows received", chunk_no, len(chunk))
                if dry_run:
                    total_rows += len(chunk)
                    continue

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
                            "retail_price_withdisc_rub": r.get(
                                "retail_price_withdisc_rub"
                            ),
                            "kiz": r.get("kiz") or None,
                            "ppvz_vw": r.get("ppvz_vw"),
                            "ppvz_vw_nds": r.get("ppvz_vw_nds"),
                            "supplier_reward": r.get("supplier_reward"),
                        }
                    )
                await _bulk_upsert(session, WbReportDetail, values, pk_cols=["rrd_id"])
                # Commit per chunk so a later 429 / cooldown / OOM does NOT
                # roll back the work already done. The next page's failure
                # then only loses the rows we have not yet seen, and the
                # script can be safely re-run to resume from where it died.
                await session.commit()
                total_rows += len(values)
                log.info(
                    "backfill: chunk %d upserted+committed, total so far %d",
                    chunk_no,
                    total_rows,
                )
        except Exception as e:
            log.error("backfill: pagination interrupted at chunk %d: %s", chunk_no, e)
            try:
                await session.rollback()
            except Exception:
                pass
            return total_rows

    log.info("backfill: DONE — %d total rows for %s..%s", total_rows, date_from, date_to)
    return total_rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", type=int, default=1, help="tenant_id (default 1)")
    p.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true", help="don't write to DB")
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    df = date.fromisoformat(args.date_from)
    dt_ = date.fromisoformat(args.date_to)
    if df > dt_:
        raise SystemExit(f"--from must be <= --to (got {df} > {dt_})")
    if (dt_ - df).days > 90:
        log.warning(
            "Window > 90 days (%d). WB may return huge response or 429 — "
            "consider splitting into smaller windows.",
            (dt_ - df).days,
        )
    rows = asyncio.run(backfill(args.tenant, df, dt_, dry_run=args.dry_run))
    print(f"\n=== backfill done: {rows} rows {'(DRY)' if args.dry_run else 'upserted'} ===")


if __name__ == "__main__":
    main()
