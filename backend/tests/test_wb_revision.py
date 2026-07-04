"""diff_and_apply (TASK-DEV-095) — версионированная переподгрузка WB-отчётов.

Проверяем на WbAdStatsDaily (узкая таблица, composite key):
  - added: новых строк нет в БД → вставлены + журнал added;
  - updated: изменённое tracked-поле → применено + old/new в журнале;
  - rejected_lower (FREEZE): понижение sum_spent → НЕ применено, журнал;
  - unchanged: идентичная строка → не попадает ни в журнал, ни в счётчики;
  - totals_delta аккумулирует дельту по полям.

nm_id/advert_id рандомизированы — тесты гоняются на живой прод-БД
(savepoint rollback в db_session).
"""
from __future__ import annotations

import secrets
from datetime import date

import pytest
from sqlalchemy import select

from app.db.models import WbAdStatsDaily, WbSyncChange, WbSyncRevision
from app.services.wb_revision import diff_and_apply

pytestmark = pytest.mark.asyncio

TRACKED = ["views", "clicks", "sum_spent", "orders"]
D1 = date(2026, 6, 1)
D2 = date(2026, 6, 2)


def _rand_id() -> int:
    return 900_000_000 + secrets.randbelow(90_000_000)


def _row(advert_id: int, nm_id: int, dt: date, **over) -> dict:
    base = {
        "advert_id": advert_id,
        "stat_date": dt,
        "nm_id": nm_id,
        "views": 100,
        "clicks": 10,
        "ctr": 10.0,
        "cpc": 5.0,
        "sum_spent": 50.0,
        "atbs": 3,
        "orders": 2,
        "cr": 20.0,
        "shks": 2,
        "sum_price": 1000.0,
    }
    base.update(over)
    return base


async def _run(session, tenant_id, rows, *, freeze=None):
    return await diff_and_apply(
        session,
        tenant_id=tenant_id,
        source="ad_stats",
        period_from=D1,
        period_to=D2,
        model=WbAdStatsDaily,
        new_rows=rows,
        key_fn=lambda r: f"ad:{r['advert_id']}:{r['stat_date']}:{r['nm_id']}",
        pk_cols=["advert_id", "stat_date", "nm_id"],
        tracked_fields=TRACKED,
        freeze_field=freeze,
        triggered_by="manual",
        existing_filter=WbAdStatsDaily.stat_date.in_([D1, D2]),
    )


async def test_added_rows(db_session, test_tenant):
    adv, nm = _rand_id(), _rand_id()
    res = await _run(db_session, test_tenant.id, [_row(adv, nm, D1)])
    assert res["added"] == 1
    assert res["changed"] == 0 and res["rejected"] == 0

    rev = (
        await db_session.execute(
            select(WbSyncRevision).where(WbSyncRevision.id == res["revision_id"])
        )
    ).scalar_one()
    assert rev.status == "done"
    assert rev.rows_added == 1
    assert rev.totals_delta["sum_spent"] == 50.0

    changes = (
        await db_session.execute(
            select(WbSyncChange).where(WbSyncChange.revision_id == rev.id)
        )
    ).scalars().all()
    assert len(changes) == 1
    assert changes[0].change_kind == "added"
    assert changes[0].old is None


async def test_updated_and_unchanged(db_session, test_tenant):
    adv, nm = _rand_id(), _rand_id()
    await _run(db_session, test_tenant.id, [_row(adv, nm, D1), _row(adv, nm, D2)])

    # D1 — sum_spent вырос (WB доначислил), D2 — без изменений.
    res = await _run(
        db_session, test_tenant.id,
        [_row(adv, nm, D1, sum_spent=75.0, clicks=15), _row(adv, nm, D2)],
    )
    assert res["added"] == 0
    assert res["changed"] == 1
    assert res["rejected"] == 0

    applied = (
        await db_session.execute(
            select(WbAdStatsDaily).where(
                WbAdStatsDaily.advert_id == adv, WbAdStatsDaily.stat_date == D1
            )
        )
    ).scalar_one()
    assert float(applied.sum_spent) == 75.0
    assert applied.clicks == 15

    change = (
        await db_session.execute(
            select(WbSyncChange).where(
                WbSyncChange.revision_id == res["revision_id"]
            )
        )
    ).scalar_one()
    assert change.change_kind == "updated"
    assert change.old["sum_spent"] == 50.0
    assert change.new["sum_spent"] == 75.0
    assert change.old["clicks"] == 10 and change.new["clicks"] == 15
    # Неизменённые tracked-поля в diff не попадают.
    assert "views" not in change.old

    rev = (
        await db_session.execute(
            select(WbSyncRevision).where(WbSyncRevision.id == res["revision_id"])
        )
    ).scalar_one()
    assert rev.totals_delta["sum_spent"] == 25.0
    assert rev.totals_delta["clicks"] == 5


async def test_freeze_rejects_lower(db_session, test_tenant):
    adv, nm = _rand_id(), _rand_id()
    await _run(db_session, test_tenant.id, [_row(adv, nm, D1)])

    # WB «забыл» расход: sum_spent 50 → 0. FREEZE не применяет, но журналит.
    res = await _run(
        db_session, test_tenant.id,
        [_row(adv, nm, D1, sum_spent=0.0)],
        freeze="sum_spent",
    )
    assert res["rejected"] == 1
    assert res["changed"] == 0

    kept = (
        await db_session.execute(
            select(WbAdStatsDaily).where(
                WbAdStatsDaily.advert_id == adv, WbAdStatsDaily.stat_date == D1
            )
        )
    ).scalar_one()
    assert float(kept.sum_spent) == 50.0  # не понижено

    change = (
        await db_session.execute(
            select(WbSyncChange).where(WbSyncChange.revision_id == res["revision_id"])
        )
    ).scalar_one()
    assert change.change_kind == "rejected_lower"
    assert change.old["sum_spent"] == 50.0
    assert change.new["sum_spent"] == 0.0


async def test_freeze_allows_growth(db_session, test_tenant):
    adv, nm = _rand_id(), _rand_id()
    await _run(db_session, test_tenant.id, [_row(adv, nm, D1)])
    res = await _run(
        db_session, test_tenant.id,
        [_row(adv, nm, D1, sum_spent=120.0)],
        freeze="sum_spent",
    )
    assert res["changed"] == 1 and res["rejected"] == 0
    kept = (
        await db_session.execute(
            select(WbAdStatsDaily).where(
                WbAdStatsDaily.advert_id == adv, WbAdStatsDaily.stat_date == D1
            )
        )
    ).scalar_one()
    assert float(kept.sum_spent) == 120.0


async def test_noop_revision(db_session, test_tenant):
    adv, nm = _rand_id(), _rand_id()
    await _run(db_session, test_tenant.id, [_row(adv, nm, D1)])
    res = await _run(db_session, test_tenant.id, [_row(adv, nm, D1)])
    assert res["added"] == 0 and res["changed"] == 0 and res["rejected"] == 0

    rev = (
        await db_session.execute(
            select(WbSyncRevision).where(WbSyncRevision.id == res["revision_id"])
        )
    ).scalar_one()
    assert rev.totals_delta is None
    changes = (
        await db_session.execute(
            select(WbSyncChange).where(WbSyncChange.revision_id == rev.id)
        )
    ).scalars().all()
    assert changes == []
