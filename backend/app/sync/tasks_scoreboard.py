"""Celery beat task: pre-aggregate manager weekly scoreboard (TASK-LEAD-087).

До этой задачи `/api/weekly-report/by-manager` делал N×`compute_dashboard`
(по числу менеджеров × 2 для WoW). На тенантах с 10+ менеджерами latency
становилась заметной (несколько секунд). Решение — nightly pre-aggregate
в таблицу `manager_weekly_scoreboard`, endpoint читает её напрямую (с
fallback на live-compute для не-агрегированных недель).

Schedule (см. `celery_app.beat_schedule['sync-manager-scoreboard-daily']`):
  ежедневно 04:30 МСК — сразу после `sync_report_detail` (04:15), чтобы
  закрытые цифры были свежими.

Логика:
  1) Для каждого tenant'а с активными менеджерами:
  2) Для каждой из последних 4 недель (понедельник UTC):
  3) Для каждого manager-user — `services.weekly_report.by_manager()` —
     возвращает уже посчитанные KPI + WoW.
  4) UPSERT в `manager_weekly_scoreboard`.

Идемпотентность — гарантирована (composite PK + UPSERT on_conflict_do_update).
Если задача упадёт mid-run, безопасно перезапустить.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.models import ManagerWeeklyScoreboard, Tenant, User
from app.services.tenant_context import set_tenant
from app.services.weekly_report import by_manager
from app.sync.celery_app import celery_app

log = get_logger(__name__)


# Сколько последних недель пред-агрегировать на каждом тике.
# 4 недели = текущая + 3 закрытые → хватает для типичного UI use-case
# (текущая + WoW + один срез назад). При расширении ретеншна — увеличить.
_WEEKS_TO_AGGREGATE = 4


def _monday(d: date) -> date:
    """Понедельник недели, в которую попадает d (UTC)."""
    return d - timedelta(days=d.weekday())


def _weeks_to_aggregate(today: date, n: int = _WEEKS_TO_AGGREGATE) -> list[date]:
    """Возвращает список понедельников последних n недель (от старой к новой)."""
    cur = _monday(today)
    return [cur - timedelta(days=7 * (n - 1 - i)) for i in range(n)]


async def _upsert_week_for_tenant(
    session,
    tenant_id: int,
    week_start: date,
) -> int:
    """Посчитать и UPSERT'нуть scoreboard для одного tenant'а × week.

    Возвращает кол-во обновлённых строк (= кол-во активных менеджеров).
    """
    items = await by_manager(session, tenant_id, week_start)
    if not items:
        return 0

    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for it in items:
        rows.append(
            {
                "tenant_id": tenant_id,
                "manager_user_id": int(it["manager_user_id"]),
                "week_start": week_start,
                "revenue": float(it.get("revenue") or 0),
                "margin": float(it.get("margin") or 0),
                "margin_pct": float(it.get("margin_pct") or 0),
                "orders": int(it.get("orders") or 0),
                "returns": int(it.get("returns") or 0),
                "prev_revenue": float(it.get("prev_revenue") or 0),
                "prev_margin_pct": float(it.get("prev_margin_pct") or 0),
                "wow_revenue_pct": (
                    float(it["wow_revenue_pct"])
                    if it.get("wow_revenue_pct") is not None
                    else None
                ),
                "wow_margin_pp": float(it.get("wow_margin_pp") or 0),
                "brands": list(it.get("brands") or []),
                "no_brands": bool(it.get("no_brands", False)),
                "manager_name": it.get("manager_name"),
                "updated_at": now,
            }
        )

    stmt = pg_insert(ManagerWeeklyScoreboard).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "manager_user_id", "week_start"],
        set_={
            "revenue": stmt.excluded.revenue,
            "margin": stmt.excluded.margin,
            "margin_pct": stmt.excluded.margin_pct,
            "orders": stmt.excluded.orders,
            "returns": stmt.excluded.returns,
            "prev_revenue": stmt.excluded.prev_revenue,
            "prev_margin_pct": stmt.excluded.prev_margin_pct,
            "wow_revenue_pct": stmt.excluded.wow_revenue_pct,
            "wow_margin_pp": stmt.excluded.wow_margin_pp,
            "brands": stmt.excluded.brands,
            "no_brands": stmt.excluded.no_brands,
            "manager_name": stmt.excluded.manager_name,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def _aggregate_tenant_async(tenant_id: int) -> dict[str, Any]:
    """Пройти по последним N неделям для tenant'а и UPSERT'нуть scoreboard."""
    from app.db.session import task_session_scope  # noqa: WPS433

    weeks = _weeks_to_aggregate(date.today())
    total_rows = 0
    async with task_session_scope() as session:
        set_tenant(session, tenant_id)
        for ws in weeks:
            n = await _upsert_week_for_tenant(session, tenant_id, ws)
            total_rows += n
        await session.commit()
    log.info(
        "sync.manager_scoreboard: tenant=%s weeks=%s rows=%s",
        tenant_id, len(weeks), total_rows,
    )
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "weeks": [w.isoformat() for w in weeks],
        "rows": total_rows,
    }


async def _aggregate_all_async() -> dict[str, Any]:
    """Iterate over all tenants that have at least one active manager."""
    from app.db.session import task_session_scope  # noqa: WPS433

    async with task_session_scope() as session:
        # Берём тенантов у которых есть хоть один active manager — иначе
        # пустой proxy через by_manager() и просто скип.
        rows = (
            await session.execute(
                select(distinct(User.tenant_id))
                .where(User.role == "manager")
                .where(User.is_active.is_(True))
            )
        ).all()
        tenant_ids = [int(r[0]) for r in rows if r[0] is not None]

    results: list[dict[str, Any]] = []
    for tid in tenant_ids:
        try:
            results.append(await _aggregate_tenant_async(tid))
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "sync.manager_scoreboard: tenant=%s failed: %s", tid, exc
            )
            results.append(
                {"status": "error", "tenant_id": tid, "error": str(exc)}
            )

    return {
        "status": "ok",
        "tenants_processed": len(results),
        "results": results,
    }


@celery_app.task(
    bind=True,
    name="sync.manager_scoreboard",
    acks_late=True,
    max_retries=3,
)
def sync_manager_scoreboard(self, tenant_id: int | None = None) -> dict[str, Any]:
    """Beat task: pre-aggregate manager weekly scoreboard.

    Если `tenant_id` указан — sync только его (для ad-hoc вызовов).
    Иначе — все tenants с активными manager'ами.

    Schedule: ежедневно 04:30 МСК (см. `celery_app.beat_schedule`).
    """
    try:
        if tenant_id is not None:
            return asyncio.run(_aggregate_tenant_async(tenant_id))
        return asyncio.run(_aggregate_all_async())
    except Exception as exc:  # noqa: BLE001
        log.exception("sync.manager_scoreboard: unexpected error — retry in 30 min")
        raise self.retry(exc=exc, countdown=1800)
