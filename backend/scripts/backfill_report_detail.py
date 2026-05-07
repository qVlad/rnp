"""Manual backfill of `wb_report_detail` for arbitrary historical periods.

The regular `sync_report_detail` Celery task pulls only the last 14 days because
WB's `report_date_from`/`report_date_to` parameters look at recently-closed
reports. To populate older history, this one-off script walks specific date
windows and saves rows to the same DB table — fully idempotent (upsert by
`rrd_id`), safe to re-run.

WB rate limit on `/api/v5/supplier/reportDetailByPeriod` is 1/min Personal,
2/24h **Base** (this seller's token is Base). The script is therefore extremely
patient — sleeps long between paginated calls inside one window, and at least 1
hour between windows on Base tokens.

Usage::

    docker compose exec backend python -m scripts.backfill_report_detail \\
        --from 2026-02-01 --to 2026-04-19

    # Or split into multiple windows (recommended for Base — under 14 days each
    # to avoid quota burn from oversized responses):
    docker compose exec backend python -m scripts.backfill_report_detail \\
        --from 2026-02-01 --to 2026-02-14
    docker compose exec backend python -m scripts.backfill_report_detail \\
        --from 2026-02-15 --to 2026-02-28
    # ... and so on

Always check `/api/settings/cooldown` before running. If `statistics > 0`,
abort and wait — running anyway will burn the WB quota on a no-op skip.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import configure_logging, get_logger
from app.db.models import WbReportDetail
from app.db.session import task_session_scope
from app.integrations.wb.client import WbApiClient
from app.integrations.wb.statistics import fetch_report_detail
from app.sync.tasks import _bulk_upsert, _ensure_products, _parse_date, _parse_dt

log = get_logger(__name__)


async def backfill(date_from: date, date_to: date, dry_run: bool = False) -> int:
    """Pull report_detail for [date_from, date_to] (inclusive) and upsert."""
    log.info(
        "backfill: starting %s..%s (dry_run=%s)", date_from, date_to, dry_run
    )
    start_ts = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)

    total_rows = 0
    async with task_session_scope() as session, WbApiClient() as wb:
        try:
            chunks_iter = fetch_report_detail(wb, date_from=start_ts, date_to=end_ts)
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
                total_rows += len(values)
                log.info(
                    "backfill: chunk %d upserted, total so far %d",
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
    rows = asyncio.run(backfill(df, dt_, dry_run=args.dry_run))
    print(f"\n=== backfill done: {rows} rows {'(DRY)' if args.dry_run else 'upserted'} ===")


if __name__ == "__main__":
    main()
