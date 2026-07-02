"""ДДС-матрица «статьи × месяцы» из операций (TASK-DEV-093).

Аналог TrueStats «Отчет ДДС»: строки = Доход (по статьям) + Нераспределённый
доход, Расход (по статьям) + Нераспределённый расход, Перевод; итоги =
Сальдо (доход − расход, переводы НЕ входят) и накопленный остаток
(Σ initial_balance счетов + сальдо с начала времён).

Группировка по «дате распределения» coalesce(alloc_date, op_date).
`include_planned=True` добавляет плановые операции (is_planned) в матрицу.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinanceAccount, FinanceImportBatch, FinanceReference, ManualOperation
from app.services.finance_accounts import account_balances


def _month_seq(date_from: date, date_to: date) -> list[str]:
    months = []
    y, m = date_from.year, date_from.month
    while (y, m) <= (date_to.year, date_to.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


async def build_cash_flow_matrix(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    group_by: str = "article",  # article | activity | counterparty
    account_ids: list[int] | None = None,
    article_ids: list[int] | None = None,
    include_planned: bool = False,
) -> dict[str, Any]:
    months = _month_seq(date_from, date_to)

    alloc = func.coalesce(ManualOperation.alloc_date, ManualOperation.op_date)
    month_expr = func.to_char(func.date_trunc("month", alloc), "YYYY-MM")

    preds = [alloc >= date_from, alloc <= date_to]
    if not include_planned:
        preds.append(ManualOperation.is_planned.is_(False))
    if account_ids:
        preds.append(ManualOperation.account_id.in_(account_ids))
    if article_ids:
        preds.append(ManualOperation.article_id.in_(article_ids))

    if group_by == "counterparty":
        key_col = ManualOperation.counterparty_id
    else:
        key_col = ManualOperation.article_id

    rows = (
        await session.execute(
            select(
                month_expr.label("month"),
                ManualOperation.op_kind,
                key_col.label("key_id"),
                func.coalesce(func.sum(ManualOperation.amount), 0).label("amt"),
            )
            .where(*preds)
            .group_by(month_expr, ManualOperation.op_kind, key_col)
        )
    ).all()

    # Справочники для label'ов (и activity при group_by=activity).
    refs = (
        await session.execute(
            select(FinanceReference.id, FinanceReference.name, FinanceReference.extra)
        )
    ).all()
    ref_name = {r.id: r.name for r in refs}
    ref_activity = {
        r.id: ((r.extra or {}).get("activity") or "operating") for r in refs
    }
    _ACTIVITY_LABELS = {
        "operating": "Операционная",
        "investing": "Инвестиционная",
        "financing": "Финансовая",
    }

    # section → key → month → amount
    data: dict[str, dict[Any, dict[str, float]]] = {"income": {}, "expense": {}, "transfer": {}}
    month_section_total: dict[str, dict[str, float]] = {"income": {}, "expense": {}}
    for r in rows:
        amt = float(r.amt or 0)
        section = r.op_kind if r.op_kind in ("income", "transfer") else "expense"
        if group_by == "activity" and section != "transfer":
            key = ref_activity.get(r.key_id, "operating") if r.key_id else "operating"
        elif section == "transfer":
            key = "__transfer__"
        else:
            key = r.key_id  # None = без статьи/контрагента → «Нераспределённый»
        bucket = data[section].setdefault(key, {})
        bucket[r.month] = bucket.get(r.month, 0.0) + amt
        if section in ("income", "expense"):
            month_section_total[section][r.month] = (
                month_section_total[section].get(r.month, 0.0) + amt
            )

    def _cells(by_month: dict[str, float], section: str) -> tuple[list[dict], float]:
        cells = []
        total = 0.0
        for m in months:
            amount = round(by_month.get(m, 0.0), 2)
            total += amount
            sec_total = month_section_total.get(section, {}).get(m, 0.0)
            pct = round(amount / sec_total * 100, 1) if sec_total else 0.0
            cells.append({"month": m, "amount": amount, "pct": pct})
        return cells, round(total, 2)

    def _label(section: str, key: Any) -> str:
        if group_by == "activity":
            return _ACTIVITY_LABELS.get(str(key), str(key))
        return ref_name.get(key, "—") if key is not None else "—"

    out_rows: list[dict[str, Any]] = []
    undistributed: dict[str, Any] = {}
    for section in ("income", "expense"):
        for key, by_month in sorted(
            data[section].items(),
            key=lambda kv: -sum(kv[1].values()),
        ):
            cells, total = _cells(by_month, section)
            if key is None and group_by != "activity":
                undistributed[section] = {"cells": cells, "total": total}
                continue
            out_rows.append(
                {
                    "section": section,
                    "key": key if isinstance(key, (int, str)) else None,
                    "label": _label(section, key),
                    "cells": cells,
                    "total": total,
                }
            )

    # Перевод — одной строкой (в сальдо не входит).
    transfer_by_month: dict[str, float] = {}
    for by_month in data["transfer"].values():
        for m, v in by_month.items():
            transfer_by_month[m] = transfer_by_month.get(m, 0.0) + v
    transfer_cells = [
        {"month": m, "amount": round(transfer_by_month.get(m, 0.0), 2), "pct": 0.0}
        for m in months
    ]

    # Сальдо по месяцам (доход − расход, факт+planned по include_planned).
    saldo = []
    for m in months:
        inc = month_section_total["income"].get(m, 0.0)
        exp = month_section_total["expense"].get(m, 0.0)
        saldo.append({"month": m, "amount": round(inc - exp, 2)})

    # Накопленный остаток: Σ initial_balance + сальдо всех ФАКТ-операций с
    # начала времён по конец каждого месяца (переводы не влияют на сумму).
    opening_rows = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (ManualOperation.op_kind == "income", ManualOperation.amount),
                            (ManualOperation.op_kind == "expense", -ManualOperation.amount),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(
                ManualOperation.is_planned.is_(False),
                func.coalesce(ManualOperation.alloc_date, ManualOperation.op_date)
                < date_from,
            )
        )
    ).scalar()
    initial_total = (
        await session.execute(
            select(func.coalesce(func.sum(FinanceAccount.initial_balance), 0)).where(
                FinanceAccount.archived.is_(False)
            )
        )
    ).scalar()
    opening_balance = float(initial_total or 0) + float(opening_rows or 0)

    cumulative = []
    running = opening_balance
    # Для накопленного остатка учитываем ТОЛЬКО факт (плановые — не деньги).
    fact_saldo_by_month: dict[str, float] = {}
    if include_planned:
        fact_rows = (
            await session.execute(
                select(
                    month_expr.label("month"),
                    func.coalesce(
                        func.sum(
                            case(
                                (ManualOperation.op_kind == "income", ManualOperation.amount),
                                (ManualOperation.op_kind == "expense", -ManualOperation.amount),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("amt"),
                )
                .where(
                    alloc >= date_from,
                    alloc <= date_to,
                    ManualOperation.is_planned.is_(False),
                )
                .group_by(month_expr)
            )
        ).all()
        fact_saldo_by_month = {r.month: float(r.amt or 0) for r in fact_rows}
    for i, m in enumerate(months):
        month_fact = (
            fact_saldo_by_month.get(m, 0.0) if include_planned else saldo[i]["amount"]
        )
        running += month_fact
        cumulative.append({"month": m, "amount": round(running, 2)})

    # Счётчики для шапки.
    no_article = (
        await session.execute(
            select(func.count(ManualOperation.id)).where(
                ManualOperation.article_id.is_(None),
                ManualOperation.op_kind != "transfer",
            )
        )
    ).scalar()
    import_errors = (
        await session.execute(
            select(func.count(FinanceImportBatch.id)).where(
                FinanceImportBatch.status == "error"
            )
        )
    ).scalar()

    balances = await account_balances(session)

    return {
        "months": months,
        "group_by": group_by,
        "opening_balance": round(opening_balance, 2),
        "accounts_balance": {
            "total": balances["total_balance"],
            "per_account": [
                {"id": a["id"], "name": a["name"], "balance": a["current_balance"]}
                for a in balances["items"]
                if not a["archived"]
            ],
        },
        "counters": {
            "ops_without_article": int(no_article or 0),
            "import_errors": int(import_errors or 0),
        },
        "rows": out_rows,
        "undistributed": undistributed,
        "transfer": {"cells": transfer_cells},
        "saldo": saldo,
        "cumulative": cumulative,
    }
