"""Автоправила категоризации операций (TASK-DEV-093).

Правило: conditions (AND-список) → actions. Политика применения:
article_id / counterparty_id проставляются ТОЛЬКО в пустые поля (не
перетираем ручную категоризацию), official_expense — всегда.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinanceAutoRule, FinanceReference, ManualOperation


def _op_matches(op: ManualOperation, conditions: list[dict[str, Any]],
                counterparty_names: dict[int, str]) -> bool:
    """AND по всем условиям. Пустой список условий — правило не матчится
    (защита от case «правило без условий красит всё подряд»)."""
    if not conditions:
        return False
    for cond in conditions:
        field = str(cond.get("field") or "")
        cmp_op = str(cond.get("op") or "equals")
        value = cond.get("value")
        if field == "counterparty":
            actual = (
                op.counterparty
                or counterparty_names.get(op.counterparty_id or -1)
                or ""
            )
        elif field == "raw_description":
            actual = op.raw_description or op.comment or ""
        elif field == "amount":
            actual = float(op.amount or 0)
        elif field == "op_kind":
            actual = op.op_kind
        else:
            return False

        if cmp_op == "equals":
            if str(actual).strip().lower() != str(value or "").strip().lower():
                return False
        elif cmp_op == "contains":
            if str(value or "").strip().lower() not in str(actual).lower():
                return False
        elif cmp_op == "gte":
            try:
                if float(actual) < float(value):
                    return False
            except (TypeError, ValueError):
                return False
        elif cmp_op == "lte":
            try:
                if float(actual) > float(value):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            return False
    return True


def apply_rule_actions(op: ManualOperation, rule: FinanceAutoRule) -> bool:
    """Применить actions к операции. Возврат — были ли изменения."""
    actions = rule.actions or {}
    changed = False
    if actions.get("article_id") and op.article_id is None:
        op.article_id = int(actions["article_id"])
        changed = True
    if actions.get("counterparty_id") and op.counterparty_id is None:
        op.counterparty_id = int(actions["counterparty_id"])
        changed = True
    if "official_expense" in actions and actions["official_expense"] is not None:
        val = bool(actions["official_expense"])
        if op.official_expense != val:
            op.official_expense = val
            changed = True
    if changed:
        op.applied_rule_id = rule.id
    return changed


async def load_enabled_rules(session: AsyncSession) -> list[FinanceAutoRule]:
    return (
        await session.execute(
            select(FinanceAutoRule)
            .where(FinanceAutoRule.enabled.is_(True))
            .order_by(FinanceAutoRule.priority, FinanceAutoRule.id)
        )
    ).scalars().all()


async def _counterparty_names(session: AsyncSession) -> dict[int, str]:
    rows = (
        await session.execute(
            select(FinanceReference.id, FinanceReference.name).where(
                FinanceReference.ref_type == "counterparty"
            )
        )
    ).all()
    return {r.id: r.name for r in rows}


async def run_rules_on_operations(
    session: AsyncSession, operations: list[ManualOperation]
) -> int:
    """Прогнать все enabled-правила по списку операций (первое сматчившееся
    по priority выигрывает). Возврат — сколько операций изменено. Без commit."""
    rules = await load_enabled_rules(session)
    if not rules:
        return 0
    cp_names = await _counterparty_names(session)
    changed = 0
    for op in operations:
        for rule in rules:
            conds = rule.conditions if isinstance(rule.conditions, list) else []
            if _op_matches(op, conds, cp_names):
                if apply_rule_actions(op, rule):
                    changed += 1
                break
    return changed


async def apply_rule_to_existing(
    session: AsyncSession, rule: FinanceAutoRule
) -> tuple[int, int]:
    """«⚡ Применить к существующим»: прогнать ОДНО правило по всем операциям
    tenant'а. Возврат (matched, updated). Без commit."""
    ops = (
        await session.execute(select(ManualOperation))
    ).scalars().all()
    cp_names = await _counterparty_names(session)
    conds = rule.conditions if isinstance(rule.conditions, list) else []
    matched = updated = 0
    for op in ops:
        if _op_matches(op, conds, cp_names):
            matched += 1
            if apply_rule_actions(op, rule):
                updated += 1
    return matched, updated
