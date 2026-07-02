"""Счета и их балансы (TASK-DEV-093).

Текущий баланс счёта НЕ хранится — вычисляется из факт-операций
(is_planned=false): initial_balance + Σincome − Σexpense − Σtransfer(из)
+ Σtransfer(в). Операции до initial_balance_date (если задана) не входят.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinanceAccount, ManualOperation


async def account_balances(
    session: AsyncSession, *, on_date: date | None = None
) -> dict[str, Any]:
    """Балансы всех счетов tenant'а (+total). on_date — включительно
    (None = все операции по сегодня и позже — фактические записи будущим
    числом тоже считаем, это редкость)."""
    accounts = (
        await session.execute(select(FinanceAccount).order_by(FinanceAccount.name))
    ).scalars().all()

    preds = [ManualOperation.is_planned.is_(False)]
    if on_date is not None:
        preds.append(ManualOperation.op_date <= on_date)

    rows = (
        await session.execute(
            select(
                ManualOperation.account_id,
                ManualOperation.transfer_account_id,
                ManualOperation.op_kind,
                ManualOperation.op_date,
                func.coalesce(func.sum(ManualOperation.amount), 0).label("amt"),
            )
            .where(*preds)
            .group_by(
                ManualOperation.account_id,
                ManualOperation.transfer_account_id,
                ManualOperation.op_kind,
                ManualOperation.op_date,
            )
        )
    ).all()

    delta: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    # min-date filter per account применяем на python-стороне (initial_balance_date
    # у каждого счёта своя — в SQL это лишний JOIN, объём операций мал).
    min_date = {a.id: a.initial_balance_date for a in accounts}

    def _apply(acc_id: int | None, amount: Decimal, sign: int, d: date) -> None:
        if acc_id is None:
            return
        mind = min_date.get(acc_id)
        if mind is not None and d < mind:
            return
        delta[acc_id] += sign * amount

    for r in rows:
        amt = Decimal(str(r.amt or 0))
        if r.op_kind == "income":
            _apply(r.account_id, amt, +1, r.op_date)
        elif r.op_kind == "transfer":
            _apply(r.account_id, amt, -1, r.op_date)
            _apply(r.transfer_account_id, amt, +1, r.op_date)
        else:  # expense (и legacy direction-only строки с op_kind='expense')
            _apply(r.account_id, amt, -1, r.op_date)

    items = []
    total = Decimal("0")
    for a in accounts:
        current = Decimal(str(a.initial_balance or 0)) + delta[a.id]
        if not a.archived:
            total += current
        items.append(
            {
                "id": a.id,
                "name": a.name,
                "initial_balance": float(a.initial_balance or 0),
                "initial_balance_date": (
                    a.initial_balance_date.isoformat() if a.initial_balance_date else None
                ),
                "archived": bool(a.archived),
                "current_balance": float(round(current, 2)),
            }
        )
    return {"items": items, "total_balance": float(round(total, 2))}
