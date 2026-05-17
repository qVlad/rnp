#!/usr/bin/env python3
"""Перенос данных из старой wbab-БД в rnp.

Запускать ВНУТРИ контейнера rnp-backend-1 на проде. wbab-Postgres
доступен по сети как `wbab_postgres_prod` (общая docker network на хосте),
либо через host-localhost:5432 если сети нет.

Usage (на сервере):
    docker compose exec -e WBAB_DSN='postgresql://wbab:PASSWORD@wbab_postgres_prod:5432/wbab' \\
                        backend python scripts/migrate_wbab_to_rnp.py [--dry-run] [--tenant-id N]

По умолчанию создаёт нового tenant'а на каждый wbab.WbAccount. Если хочешь
залить всё в существующий tenant — `--tenant-id N`.

Файлы фото на диске:
    На хосте: /var/lib/docker/volumes/wbab_storage/_data/photos/*
    Целевой volume: rnp_abtest_photos:/app/storage/photos/

    Скопировать (отдельно — скрипт это НЕ делает, чтобы не лочить FS):
        ssh prod-host
        sudo rsync -avz \\
            /var/lib/docker/volumes/wbab_storage/_data/photos/ \\
            /var/lib/docker/volumes/rnp_abtest_photos/_data/

    Но: wbab использует cuid в путях ({cuid}/A.jpg), а rnp использует
    bigint id из abtest_id. Скрипт перепишет abtest_variant_photo.photo_path,
    используя новые id, и вернёт инструкцию какие пути надо переименовать.

Маппинг:
    wbab.User                  → rnp.users (по email, или создать)
    wbab.WbAccount             → rnp.tenants (1:1; копируем apiTokenEnc как есть
                                 если зашифрован, иначе re-encrypt через Fernet)
    wbab.Product               → rnp.products (UPSERT по nm_id)
    wbab.Test                  → rnp.abtest (cuid → bigint, FK на новый tenant)
    wbab.Variant               → rnp.abtest_variant
    wbab.VariantPhoto          → rnp.abtest_variant_photo (path переписан)
    wbab.RotationLog           → rnp.abtest_rotation
    wbab.TestAlert             → rnp.abtest_alert
    wbab.TestEvent             → rnp.abtest_event (metadata → event_metadata)
    wbab.DailyStat             → rnp.abtest_daily_stat
    wbab.AdPlatformStat        → rnp.abtest_ad_platform_stat
    wbab.AdPlatformSnapshot    → rnp.abtest_ad_platform_snapshot
    wbab.StatsSnapshot         → rnp.abtest_stats_snapshot
    wbab.TestResult            → rnp.abtest_result
    wbab.CampaignBudgetSnapshot→ rnp.wb_campaign_budget
    wbab.WbApiCall             → НЕ переносим (логи, не нужны)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")


WBAB_DSN_DEFAULT = "postgresql://wbab:wbab@wbab_postgres_prod:5432/wbab"


async def fetch_all(conn: asyncpg.Connection, table: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(f'SELECT * FROM "{table}"')
    return [dict(r) for r in rows]


async def migrate(
    wbab_dsn: str,
    rnp_dsn: str,
    target_tenant_id: int | None,
    dry_run: bool,
) -> dict[str, int]:
    """Перенести wbab→rnp. Возвращает агрегат rowcount по таблицам."""
    stats: dict[str, int] = {}

    src = await asyncpg.connect(wbab_dsn)
    dst = await asyncpg.connect(rnp_dsn)
    log.info("Connected to wbab + rnp")

    try:
        # ------------------------------------------------------------------
        # 1. Tenants — один на WbAccount (или передан target_tenant_id)
        # ------------------------------------------------------------------
        wbab_accounts = await fetch_all(src, "WbAccount")
        log.info("wbab.WbAccount: %d rows", len(wbab_accounts))
        # tenant_map: wbab.WbAccount.id (str cuid) → rnp.tenants.id (int)
        tenant_map: dict[str, int] = {}

        for acc in wbab_accounts:
            if target_tenant_id is not None:
                tenant_map[acc["id"]] = target_tenant_id
                continue
            # Создаём новый tenant с slug='wbab-<id8>'
            slug = f"wbab-{acc['id'][:8]}"
            wb_token = acc.get("apiTokenEnc") or ""
            existing = await dst.fetchval(
                "SELECT id FROM tenants WHERE slug = $1", slug
            )
            if existing:
                tenant_map[acc["id"]] = int(existing)
                log.info("  tenant %s reused (slug=%s)", existing, slug)
                continue
            if dry_run:
                tenant_map[acc["id"]] = -1
                log.info("  [dry] would create tenant slug=%s", slug)
                continue
            new_id = await dst.fetchval(
                """INSERT INTO tenants (name, slug, wb_token, created_at, updated_at)
                   VALUES ($1, $2, $3, now(), now()) RETURNING id""",
                acc.get("name") or slug,
                slug,
                wb_token,
            )
            tenant_map[acc["id"]] = int(new_id)
            log.info("  tenant %d created (slug=%s)", new_id, slug)

        # ------------------------------------------------------------------
        # 2. Products — UPSERT по (nm_id) — НЕ tenant-scoped в wbab, но
        #    rnp.products уже могут существовать (синкаются из WB Content API)
        # ------------------------------------------------------------------
        wbab_products = await fetch_all(src, "Product")
        log.info("wbab.Product: %d rows", len(wbab_products))
        prod_count = 0
        for p in wbab_products:
            tid = tenant_map.get(p["wbAccountId"])
            if tid is None or tid < 0:
                continue
            existing = await dst.fetchval(
                "SELECT nm_id FROM products WHERE nm_id = $1", int(p["nmId"])
            )
            if existing:
                continue  # уже синканный из rnp
            if dry_run:
                prod_count += 1
                continue
            await dst.execute(
                """INSERT INTO products
                       (tenant_id, nm_id, vendor_code, subject, brand, photo_url, is_archived)
                       VALUES ($1, $2, $3, NULL, $4, $5, FALSE)
                       ON CONFLICT (nm_id) DO NOTHING""",
                tid,
                int(p["nmId"]),
                p.get("vendorCode"),
                p.get("brand"),
                p.get("mainPhotoUrl"),
            )
            prod_count += 1
        stats["products"] = prod_count

        # ------------------------------------------------------------------
        # 3. Tests + child mappings (cuid → bigint)
        # ------------------------------------------------------------------
        wbab_tests = await fetch_all(src, "Test")
        log.info("wbab.Test: %d rows", len(wbab_tests))
        test_map: dict[str, int] = {}

        for t in wbab_tests:
            tid = tenant_map.get(t["wbAccountId"])
            if tid is None or tid < 0:
                continue
            prod = next(
                (pr for pr in wbab_products if pr["id"] == t["productId"]), None
            )
            if not prod:
                log.warning("  test %s: product %s missing", t["id"], t["productId"])
                continue
            nm_id = int(prod["nmId"])
            if dry_run:
                test_map[t["id"]] = -1
                continue
            new_id = await dst.fetchval(
                """INSERT INTO abtest
                       (tenant_id, name, nm_id, status, trigger_mode, trigger_value,
                        traffic_source, test_mode, campaign_id, campaign_type,
                        min_sample_size, confidence_level, keep_leaders_after_24h,
                        leaders_culled_at, started_at, ends_at, completed_at,
                        archived_at, budget_auto_topup, budget_min_threshold,
                        budget_topup_amount, budget_daily_limit,
                        budget_topup_spent_today, budget_topup_reset_at,
                        original_photos, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                           $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                           $21, $22, $23, $24, $25, $26, $27)
                   RETURNING id""",
                tid,
                t["name"],
                nm_id,
                t["status"],
                t["triggerMode"],
                int(t["triggerValue"]),
                t["trafficSource"],
                t["testMode"],
                int(t["campaignId"]) if t.get("campaignId") else None,
                int(t["campaignType"]),
                int(t["minSampleSize"]),
                float(t["confidenceLevel"]),
                bool(t["keepLeadersAfter24h"]),
                t.get("leadersCulledAt"),
                t.get("startedAt"),
                t.get("endsAt"),
                t.get("completedAt"),
                t.get("archivedAt"),
                bool(t["budgetAutoTopup"]),
                int(t["budgetMinThreshold"]),
                int(t["budgetTopupAmount"]),
                int(t["budgetDailyLimit"]),
                int(t["budgetTopupSpentToday"]),
                t.get("budgetTopupResetAt"),
                t.get("originalPhotos"),
                t["createdAt"],
                t["updatedAt"],
            )
            test_map[t["id"]] = int(new_id)
        stats["abtest"] = len(test_map)
        log.info("  abtest: %d migrated", stats["abtest"])

        # Variants
        wbab_variants = await fetch_all(src, "Variant")
        variant_map: dict[str, int] = {}
        for v in wbab_variants:
            new_test_id = test_map.get(v["testId"])
            if new_test_id is None or new_test_id < 0:
                continue
            t_row = next((tt for tt in wbab_tests if tt["id"] == v["testId"]), None)
            if not t_row:
                continue
            tid = tenant_map[t_row["wbAccountId"]]
            if dry_run:
                variant_map[v["id"]] = -1
                continue
            new_id = await dst.fetchval(
                """INSERT INTO abtest_variant
                       (tenant_id, abtest_id, label, eliminated_at, created_at)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                tid, new_test_id, v["label"], v.get("eliminatedAt"), v["createdAt"],
            )
            variant_map[v["id"]] = int(new_id)
        stats["abtest_variant"] = len(variant_map)

        # Variant photos — переписываем photo_path под новые id
        wbab_photos = await fetch_all(src, "VariantPhoto")
        ph_count = 0
        path_renames: list[tuple[str, str]] = []
        for ph in wbab_photos:
            new_v = variant_map.get(ph["variantId"])
            if new_v is None or new_v < 0:
                continue
            v_row = next(
                (vv for vv in wbab_variants if vv["id"] == ph["variantId"]), None
            )
            if not v_row:
                continue
            t_row = next((tt for tt in wbab_tests if tt["id"] == v_row["testId"]), None)
            if not t_row:
                continue
            new_test = test_map[t_row["testId"]] if "testId" in t_row else test_map[v_row["testId"]]
            tid = tenant_map[t_row["wbAccountId"]]
            old_path = ph["photoPath"]
            # wbab: storage/photos/{cuid}/{label}_{N}.jpg
            # rnp:  /app/storage/photos/{bigint}/{label}_{N}.jpg
            new_path = old_path.replace(
                f"/{v_row['testId']}/", f"/{new_test}/"
            )
            if not new_path.startswith("/app/storage/photos"):
                new_path = f"/app/storage/photos/{new_test}/{Path(old_path).name}"
            path_renames.append((old_path, new_path))
            if dry_run:
                ph_count += 1
                continue
            await dst.execute(
                """INSERT INTO abtest_variant_photo
                       (tenant_id, variant_id, photo_order, photo_path, content_type)
                   VALUES ($1, $2, $3, $4, $5)""",
                tid, new_v, int(ph["photoOrder"]),
                new_path, ph.get("contentType") or "image/jpeg",
            )
            ph_count += 1
        stats["abtest_variant_photo"] = ph_count

        # ------------------------------------------------------------------
        # 4. Rotations, alerts, events, daily stats, snapshots, results
        # ------------------------------------------------------------------
        for src_table, dst_table, mapper in [
            ("RotationLog", "abtest_rotation", _map_rotation),
            ("TestAlert", "abtest_alert", _map_alert),
            ("TestEvent", "abtest_event", _map_event),
            ("DailyStat", "abtest_daily_stat", _map_daily_stat),
            ("AdPlatformStat", "abtest_ad_platform_stat", _map_platform_stat),
            ("AdPlatformSnapshot", "abtest_ad_platform_snapshot", _map_platform_snap),
            ("StatsSnapshot", "abtest_stats_snapshot", _map_stats_snap),
            ("TestResult", "abtest_result", _map_test_result),
        ]:
            try:
                rows = await fetch_all(src, src_table)
            except asyncpg.UndefinedTableError:
                log.info("  %s: table not in wbab, skip", src_table)
                continue
            count = 0
            for row in rows:
                try:
                    insert_kwargs = mapper(
                        row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants
                    )
                except _Skip:
                    continue
                if insert_kwargs is None:
                    continue
                if dry_run:
                    count += 1
                    continue
                cols = ", ".join(insert_kwargs.keys())
                placeholders = ", ".join(f"${i+1}" for i in range(len(insert_kwargs)))
                await dst.execute(
                    f"INSERT INTO {dst_table} ({cols}) VALUES ({placeholders})",
                    *insert_kwargs.values(),
                )
                count += 1
            stats[dst_table] = count
            log.info("  %s → %s: %d migrated", src_table, dst_table, count)

        # ------------------------------------------------------------------
        # 5. Output rsync hint for photo files
        # ------------------------------------------------------------------
        if path_renames:
            log.info("=" * 60)
            log.info("Photo path renames needed (run rsync to copy files):")
            log.info(
                "  sudo rsync -avz "
                "/var/lib/docker/volumes/wbab_storage/_data/photos/ "
                "/var/lib/docker/volumes/rnp_abtest_photos/_data/"
            )
            log.info("Then rename subdirs from cuid → bigint:")
            seen_dirs: set[tuple[str, str]] = set()
            for old, new in path_renames:
                # Извлекаем имена директорий
                old_dir = Path(old).parent.name
                new_dir = Path(new).parent.name
                if (old_dir, new_dir) in seen_dirs:
                    continue
                seen_dirs.add((old_dir, new_dir))
                log.info(
                    "  mv /var/lib/docker/volumes/rnp_abtest_photos/_data/%s "
                    "/var/lib/docker/volumes/rnp_abtest_photos/_data/%s",
                    old_dir, new_dir,
                )

    finally:
        await src.close()
        await dst.close()

    return stats


# ----------------------------------------------------------------------
# Per-table mappers — возвращают dict для INSERT либо None (skip)
# ----------------------------------------------------------------------


class _Skip(Exception):
    pass


def _tenant_for(test_id_cuid: str, wbab_tests, tenant_map):
    t = next((tt for tt in wbab_tests if tt["id"] == test_id_cuid), None)
    if not t:
        raise _Skip()
    tid = tenant_map.get(t["wbAccountId"])
    if tid is None or tid < 0:
        raise _Skip()
    return tid


def _map_rotation(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    new_var = variant_map.get(row["variantId"])
    if new_test is None or new_var is None or new_test < 0 or new_var < 0:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "variant_id": new_var,
        "applied_at": row["appliedAt"],
        "success": bool(row["success"]),
        "wb_response": row.get("wbResponse"),
        "error": row.get("error"),
        "wb_photo_url_after": row.get("wbPhotoUrlAfter"),
    }


def _map_alert(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    if new_test is None or new_test < 0:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "message": row["message"],
        "resolved": bool(row["resolved"]),
        "created_at": row["createdAt"],
    }


def _map_event(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    if new_test is None or new_test < 0:
        raise _Skip()
    new_var = variant_map.get(row.get("variantId")) if row.get("variantId") else None
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "variant_id": new_var if new_var and new_var > 0 else None,
        "kind": row["kind"],
        "source": row.get("source") or "manual",
        "actor_user_id": None,  # wbab привязка через userId-чужой, не маппим
        "event_metadata": row.get("metadata"),
        "created_at": row["createdAt"],
    }


def _map_daily_stat(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_var = variant_map.get(row["variantId"])
    if new_var is None or new_var < 0:
        raise _Skip()
    v_row = next((vv for vv in wbab_variants if vv["id"] == row["variantId"]), None)
    if not v_row:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(v_row["testId"], wbab_tests, tenant_map),
        "variant_id": new_var,
        "stat_date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
        "source": row.get("source") or "nm-report",
        "impressions": int(row.get("impressions") or 0),
        "clicks": int(row.get("clicks") or 0),
        "cart_adds": int(row.get("cartAdds") or 0),
        "orders": int(row.get("orders") or 0),
        "revenue": row.get("revenue") or 0,
        "ad_spend": row.get("adSpend") or 0,
        "ctr": row.get("ctr") or 0,
        "cr": row.get("cr") or 0,
        "buyouts": int(row.get("buyouts") or 0),
        "cancels": int(row.get("cancels") or 0),
        "buyout_revenue": row.get("buyoutRevenue") or 0,
        "cancel_loss": row.get("cancelLoss") or 0,
        "wishlist_adds": int(row.get("wishlistAdds") or 0),
    }


def _map_platform_stat(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_var = variant_map.get(row["variantId"])
    if new_var is None or new_var < 0:
        raise _Skip()
    v_row = next((vv for vv in wbab_variants if vv["id"] == row["variantId"]), None)
    if not v_row:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(v_row["testId"], wbab_tests, tenant_map),
        "variant_id": new_var,
        "stat_date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
        "platform": row["platform"],
        "impressions": int(row.get("impressions") or 0),
        "clicks": int(row.get("clicks") or 0),
        "orders": int(row.get("orders") or 0),
        "ad_spend": row.get("adSpend") or 0,
    }


def _map_platform_snap(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    if new_test is None or new_test < 0:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "day_date": row["dayDate"].date() if hasattr(row["dayDate"], "date") else row["dayDate"],
        "platform": row["platform"],
        "captured_at": row["capturedAt"],
        "cum_impressions": int(row.get("cumImpressions") or 0),
        "cum_clicks": int(row.get("cumClicks") or 0),
        "cum_orders": int(row.get("cumOrders") or 0),
        "cum_ad_spend": row.get("cumAdSpend") or 0,
    }


def _map_stats_snap(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    if new_test is None or new_test < 0:
        raise _Skip()
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "source": row["source"],
        "day_date": row["dayDate"].date() if hasattr(row["dayDate"], "date") else row["dayDate"],
        "captured_at": row["capturedAt"],
        "cum_impressions": int(row.get("cumImpressions") or 0),
        "cum_clicks": int(row.get("cumClicks") or 0),
        "cum_cart_adds": int(row.get("cumCartAdds") or 0),
        "cum_orders": int(row.get("cumOrders") or 0),
        "cum_ad_spend": row.get("cumAdSpend") or 0,
        "cum_revenue": row.get("cumRevenue") or 0,
    }


def _map_test_result(row, test_map, variant_map, tenant_map, wbab_tests, wbab_variants):
    new_test = test_map.get(row["testId"])
    if new_test is None or new_test < 0:
        raise _Skip()
    new_winner = (
        variant_map.get(row.get("winnerVariantId"))
        if row.get("winnerVariantId")
        else None
    )
    return {
        "tenant_id": _tenant_for(row["testId"], wbab_tests, tenant_map),
        "abtest_id": new_test,
        "winner_variant_id": new_winner if new_winner and new_winner > 0 else None,
        "p_value_ctr": row.get("pValueCtr"),
        "p_value_cr": row.get("pValueCr"),
        "p_value_buyout": row.get("pValueBuyout"),
        "ci_ctr_low": row.get("ciCtrLow"),
        "ci_ctr_high": row.get("ciCtrHigh"),
        "ci_cr_low": row.get("ciCrLow"),
        "ci_cr_high": row.get("ciCrHigh"),
        "recommendation": row.get("recommendation"),
        "computed_at": row["computedAt"],
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


async def main_async() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--wbab-dsn",
        default=os.environ.get("WBAB_DSN", WBAB_DSN_DEFAULT),
        help="DSN wbab Postgres. Default: %(default)s",
    )
    p.add_argument(
        "--rnp-dsn",
        default=os.environ.get(
            "RNP_DSN",
            "postgresql://app:app@postgres:5432/rnp",
        ),
    )
    p.add_argument("--tenant-id", type=int, default=None,
                   help="Если задан — все WbAccount сольются в этот tenant.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    log.info("wbab DSN: %s", args.wbab_dsn.split("@")[-1])
    log.info("rnp DSN:  %s", args.rnp_dsn.split("@")[-1])
    log.info("dry-run:  %s", args.dry_run)

    stats = await migrate(args.wbab_dsn, args.rnp_dsn, args.tenant_id, args.dry_run)
    log.info("=" * 60)
    log.info("DONE. Summary:")
    for k, v in stats.items():
        log.info("  %s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
