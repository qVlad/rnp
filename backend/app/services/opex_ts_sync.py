"""Синк OPEX из TrueStats (TASK-DEV-077): берём методологию TS — полные
операционные расходы (ФОТ/аренда/подписки) с распределением по аккаунтам, пишем
ДОЛЮ нашего кабинета в `opex_entries`.

Гранулярность — МЕСЯЦ (как operation/list у TS). Одна запись OpexEntry на статью
за месяц, dated последним днём месяца, `comment='ts-sync:<YYYY-MM>'` (маркер для
идемпотентности — повторный синк удаляет старые ts-sync записи месяца и пишет
заново). У каждой записи — tenant-allocation weight=1.0 (инвариант миграции 0055).

Распределение (из reverse-engineering, TASK-DEV-077):
  • equal        — сумма / число аккаунтов (если наш аккаунт в списке);
  • proportional — сумма × (наша реализация / Σ реализаций аккаунтов) за месяц;
  • один аккаунт — вся сумма.
Учитываем только operationType='expense', activityType='operational',
isConfirmed=true, isPlanned=false.

Конфиг (AppSetting per-tenant): `ts_auth_token` (120-hex), `ts_account_id`
(id кабинета в TS, напр. Onyx=25143).
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AppSetting, OpexCategory, OpexEntry, OpexEntryAllocation
from app.integrations.truestats import account_realisation, operation_list
from app.services.tenant_context import get_tenant

log = get_logger(__name__)

_CAT_PREFIX = "TS: "  # префикс категорий, созданных синком


async def _setting(session: AsyncSession, tenant_id: int, key: str) -> str | None:
    row = (
        await session.execute(
            select(AppSetting.value).where(
                AppSetting.tenant_id == tenant_id, AppSetting.key == key
            )
        )
    ).scalar_one_or_none()
    return (row or "").strip() or None


async def compute_ts_opex_breakdown(
    token: str, ts_account_id: int, date_from: date, date_to: date
) -> tuple[dict[str, float], dict[str, Any]]:
    """Доля нашего аккаунта в OPEX TS за период, по статьям. Возврат (by_cat, meta)."""
    items = await operation_list(
        token, date_from=date_from, date_to=date_to, account_id=ts_account_id
    )
    exp = [
        it for it in items
        if it.get("operationType") == "expense"
        and it.get("activityType") == "operational"
        and it.get("isConfirmed")
        and not it.get("isPlanned")
    ]
    # Реализация по аккаунтам, участвующим в proportional-распределении.
    prop_ids: set[int] = set()
    for it in exp:
        d = it.get("distribution") or {}
        if d.get("method") == "proportional":
            for e in (d.get("entities") or []):
                prop_ids.add(int(e["id"]))
    rev: dict[int, float] = {}
    for eid in prop_ids:
        rev[eid] = await account_realisation(
            token, date_from=date_from, date_to=date_to, account_id=eid
        )

    by_cat: dict[str, float] = {}
    n_equal = n_prop = n_single = n_skipped = 0
    for it in exp:
        d = it.get("distribution") or {}
        ents = d.get("entities") or []
        ids = [int(e["id"]) for e in ents]
        if ts_account_id not in ids:
            n_skipped += 1
            continue
        amount = float(it.get("amount") or 0)
        method = d.get("method")
        if len(ids) == 1:
            share = amount
            n_single += 1
        elif method == "proportional":
            tot = sum(rev.get(i, 0.0) for i in ids)
            share = amount * (rev.get(ts_account_id, 0.0) / tot) if tot > 0 else 0.0
            n_prop += 1
        else:  # equal (или неизвестный → делим поровну как безопасный дефолт)
            share = amount / len(ids) if ids else 0.0
            n_equal += 1
        cat = (it.get("category") or {}).get("name") or "Прочее"
        by_cat[cat] = by_cat.get(cat, 0.0) + share

    meta = {
        "items_total": len(items),
        "expense_operational": len(exp),
        "equal": n_equal, "proportional": n_prop, "single_account": n_single,
        "skipped_not_our_account": n_skipped,
        "proportional_basis": "realisation",
    }
    return {k: round(v, 2) for k, v in by_cat.items()}, meta


async def _get_or_create_category(session: AsyncSession, tenant_id: int, name: str) -> int:
    full = _CAT_PREFIX + name
    cid = (
        await session.execute(
            select(OpexCategory.id).where(
                OpexCategory.tenant_id == tenant_id, OpexCategory.name == full
            )
        )
    ).scalar_one_or_none()
    if cid is not None:
        return int(cid)
    cat = OpexCategory(
        tenant_id=tenant_id, name=full, kind="expense", in_operating=True
    )
    session.add(cat)
    await session.flush()
    return int(cat.id)


async def sync_ts_opex(
    session: AsyncSession, *, date_from: date, date_to: date
) -> dict[str, Any]:
    """Синк OPEX из TS за период [date_from, date_to] (помесячно). Идемпотентно.

    tenant_id берётся из session (set_tenant). Возвращает разбивку + итог.
    """
    tenant_id = get_tenant(session)
    if tenant_id is None:
        return {"error": "tenant_id не задан"}
    # Токен хранится зашифрованным (Fernet, как wb_token) в `ts_auth_token_enc`.
    from app.services.secrets_crypto import decrypt as _decrypt

    enc = await _setting(session, tenant_id, "ts_auth_token_enc")
    token = _decrypt(enc) if enc else None
    acc_raw = await _setting(session, tenant_id, "ts_account_id")
    if not token or not acc_raw or not acc_raw.isdigit():
        return {"error": "не заданы ts_auth_token_enc (POST /api/opex/ts-token) и/или ts_account_id"}
    ts_account_id = int(acc_raw)

    by_cat, meta = await compute_ts_opex_breakdown(token, ts_account_id, date_from, date_to)

    # Идемпотентность: убрать прежние ts-sync записи этого периода.
    marker = f"ts-sync:{date_from.isoformat()}..{date_to.isoformat()}"
    old_ids = (
        await session.execute(
            select(OpexEntry.id).where(
                OpexEntry.tenant_id == tenant_id,
                OpexEntry.comment == marker,
            )
        )
    ).scalars().all()
    if old_ids:
        await session.execute(
            delete(OpexEntryAllocation).where(OpexEntryAllocation.opex_id.in_(old_ids))
        )
        await session.execute(delete(OpexEntry).where(OpexEntry.id.in_(old_ids)))

    # Записываем по статье, dated концом периода.
    entry_dt = date_to
    total = 0.0
    for cat_name, amount in by_cat.items():
        if abs(amount) < 0.005:
            continue
        cid = await _get_or_create_category(session, tenant_id, cat_name)
        entry = OpexEntry(
            tenant_id=tenant_id, entry_date=entry_dt, category_id=cid,
            amount=Decimal(str(round(amount, 2))), contractor="TrueStats sync",
            comment=marker,
        )
        session.add(entry)
        await session.flush()
        session.add(OpexEntryAllocation(
            tenant_id=tenant_id, opex_id=entry.id, scope_type="tenant",
            scope_value=None, weight=Decimal("1.0"),
        ))
        total += amount

    return {
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "ts_account_id": ts_account_id,
        "by_category": by_cat,
        "total": round(total, 2),
        "meta": meta,
    }


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)
