"""Версионированная переподгрузка WB-отчётов (TASK-DEV-095).

`diff_and_apply()` — универсальный проход: свежие строки от WB сравниваются
с сохранёнными, изменения применяются в ОСНОВНУЮ таблицу (актуальность),
а прежние значения фиксируются в `wb_sync_change` (история). Обновления,
понижающие «защищённое» поле (FREEZE — Правило 3.5: WB иногда отдаёт
занулённую/усечённую историю), НЕ применяются, но тоже журналируются
(change_kind=rejected_lower) — расхождение видно, данные не портятся.

Ключевые поля сравниваются с допуском 0.01 (float/Decimal шум).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import WbSyncChange, WbSyncRevision

log = get_logger(__name__)

# Не раздуваем журнал: если ревизия принесла больше изменений — режем хвост
# (счётчики в ревизии остаются точными).
MAX_CHANGES_PER_REVISION = 20_000


def _norm(v: Any) -> Any:
    """Нормализация значения для сравнения/JSONB.

    datetime приводим к naive-UTC: asyncpg отдаёт из БД tz-aware (+00:00),
    а свежие строки WB — naive с тем же wall-clock. Без выравнивания каждый
    заполненный cancel_dt давал фантомный diff (24k шумовых «updated» на
    первом же прогоне orders-refetch).
    """
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _differs(a: Any, b: Any) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a or 0) - float(b or 0)) > 0.01
        except (TypeError, ValueError):
            return a != b
    return a != b


async def diff_and_apply(
    session: AsyncSession,
    *,
    tenant_id: int,
    source: str,
    period_from: date,
    period_to: date,
    model: Any,
    new_rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
    pk_cols: list[str],
    tracked_fields: list[str],
    freeze_field: str | None = None,
    triggered_by: str = "beat",
    existing_filter: Any | None = None,
) -> dict[str, int]:
    """Сравнить свежие строки с БД, применить и записать ревизию.

    - `key_fn(row) -> str` — entity_key строки (для журнала).
    - `pk_cols` — конфликтный ключ upsert'а основной таблицы.
    - `tracked_fields` — какие поля сравниваем/журналируем.
    - `freeze_field` — если задано: новое значение поля НИЖЕ сохранённого >0
      → строка НЕ применяется (rejected_lower), diff в журнал.
    - `existing_filter` — SQLAlchemy-предикат выборки существующих строк
      (обычно по периоду); при None существующие ищутся по PK новых строк.

    Возвращает счётчики. Commit делает caller.
    """
    from app.sync.tasks import _bulk_upsert  # noqa: WPS433 — реюз чанк-upsert'а

    revision = WbSyncRevision(
        tenant_id=tenant_id,
        source=source,
        period_from=period_from,
        period_to=period_to,
        rows_fetched=len(new_rows),
        triggered_by=triggered_by,
    )
    session.add(revision)
    await session.flush()

    # Существующие строки: по периоду (дешевле и полнее, ловит и удалённые
    # у WB строки — их мы НЕ трогаем, Правило 3.5 «пустой ответ ≠ delete»).
    stmt = select(model)
    if existing_filter is not None:
        stmt = stmt.where(existing_filter)
        existing_objs = (await session.execute(stmt)).scalars().all()
    else:
        existing_objs = []
        # По PK новых строк, чанками (pitfall #7).
        if new_rows and len(pk_cols) == 1:
            pk = pk_cols[0]
            keys = [r[pk] for r in new_rows]
            col = getattr(model, pk)
            for i in range(0, len(keys), 5000):
                part = (
                    await session.execute(stmt.where(col.in_(keys[i:i + 5000])))
                ).scalars().all()
                existing_objs.extend(part)

    def obj_key(obj: Any) -> tuple:
        return tuple(_norm(getattr(obj, c)) for c in pk_cols)

    def row_key(row: dict[str, Any]) -> tuple:
        return tuple(_norm(row.get(c)) for c in pk_cols)

    existing_by_pk = {obj_key(o): o for o in existing_objs}

    to_apply: list[dict[str, Any]] = []
    changes: list[WbSyncChange] = []
    added = changed = rejected = 0
    totals_delta: dict[str, float] = {}

    def bump_delta(field: str, old_v: Any, new_v: Any) -> None:
        try:
            d = float(_norm(new_v) or 0) - float(_norm(old_v) or 0)
        except (TypeError, ValueError):
            return
        if d:
            totals_delta[field] = round(totals_delta.get(field, 0.0) + d, 2)

    for row in new_rows:
        obj = existing_by_pk.get(row_key(row))
        if obj is None:
            added += 1
            to_apply.append(row)
            if len(changes) < MAX_CHANGES_PER_REVISION:
                changes.append(WbSyncChange(
                    tenant_id=tenant_id, revision_id=revision.id, source=source,
                    entity_key=key_fn(row)[:128], change_kind="added",
                    old=None,
                    new={f: _norm(row.get(f)) for f in tracked_fields if row.get(f) not in (None, 0, 0.0, "")},
                ))
            for f in tracked_fields:
                bump_delta(f, None, row.get(f))
            continue

        diff_old: dict[str, Any] = {}
        diff_new: dict[str, Any] = {}
        for f in tracked_fields:
            if f not in row:
                continue
            old_v = getattr(obj, f, None)
            if _differs(old_v, row[f]):
                diff_old[f] = _norm(old_v)
                diff_new[f] = _norm(row[f])
        if not diff_old:
            continue  # строка не изменилась

        # FREEZE: понижение защищённого поля не применяем.
        if freeze_field and freeze_field in diff_new:
            old_fv = float(diff_old.get(freeze_field) or 0)
            new_fv = float(diff_new.get(freeze_field) or 0)
            if new_fv < old_fv and old_fv > 0:
                rejected += 1
                if len(changes) < MAX_CHANGES_PER_REVISION:
                    changes.append(WbSyncChange(
                        tenant_id=tenant_id, revision_id=revision.id, source=source,
                        entity_key=key_fn(row)[:128], change_kind="rejected_lower",
                        old=diff_old, new=diff_new,
                    ))
                continue

        changed += 1
        to_apply.append(row)
        if len(changes) < MAX_CHANGES_PER_REVISION:
            changes.append(WbSyncChange(
                tenant_id=tenant_id, revision_id=revision.id, source=source,
                entity_key=key_fn(row)[:128], change_kind="updated",
                old=diff_old, new=diff_new,
            ))
        for f in diff_old:
            bump_delta(f, diff_old[f], diff_new[f])

    if to_apply:
        await _bulk_upsert(session, model, to_apply, pk_cols=pk_cols)
    for ch in changes:
        session.add(ch)

    revision.rows_added = added
    revision.rows_changed = changed
    revision.rows_rejected = rejected
    revision.totals_delta = totals_delta or None
    revision.status = "done"
    revision.finished_at = datetime.now(timezone.utc)
    await session.flush()
    log.info(
        "wb-revision %s tenant=%s %s..%s: fetched=%d added=%d changed=%d rejected=%d",
        source, tenant_id, period_from, period_to, len(new_rows), added, changed, rejected,
    )
    return {
        "revision_id": revision.id,
        "fetched": len(new_rows),
        "added": added,
        "changed": changed,
        "rejected": rejected,
    }
