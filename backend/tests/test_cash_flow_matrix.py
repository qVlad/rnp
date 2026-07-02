"""Тесты ДДС-матрицы, балансов счетов и автоправил (TASK-DEV-093)."""
from __future__ import annotations

import secrets
from datetime import date

import pytest
from sqlalchemy import select

from app.db.models import (
    FinanceAccount,
    FinanceAutoRule,
    FinanceReference,
    ManualOperation,
    Tenant,
)
from app.services.cash_flow_matrix import build_cash_flow_matrix
from app.services.finance_accounts import account_balances
from app.services.finance_rules import run_rules_on_operations
from app.services.tenant_context import set_tenant


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fin_tenant(db_session):
    """Изолированный tenant + счёт + статьи + операции."""
    set_tenant(db_session, None)
    suffix = secrets.token_hex(4)
    tenant = Tenant(name=f"Fin {suffix}", slug=f"fin-{suffix}")
    db_session.add(tenant)
    await db_session.flush()
    set_tenant(db_session, int(tenant.id))

    acc1 = FinanceAccount(tenant_id=tenant.id, name="ТБанк", initial_balance=100000)
    acc2 = FinanceAccount(tenant_id=tenant.id, name="ВТБ", initial_balance=0)
    art_wb = FinanceReference(
        tenant_id=tenant.id, ref_type="expense_category", name="ВБ доход",
        extra={"op_type": "income", "activity": "operating"},
    )
    art_rent = FinanceReference(
        tenant_id=tenant.id, ref_type="expense_category", name="Аренда",
        extra={"op_type": "expense", "activity": "operating"},
    )
    db_session.add_all([acc1, acc2, art_wb, art_rent])
    await db_session.flush()

    ops = [
        # июнь: доход 50к (ВБ), расход 20к (Аренда), расход 5к без статьи
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 5),
                        direction="income", op_kind="income", amount=50000,
                        account_id=acc1.id, article_id=art_wb.id),
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 10),
                        direction="expense", op_kind="expense", amount=20000,
                        account_id=acc1.id, article_id=art_rent.id),
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 12),
                        direction="expense", op_kind="expense", amount=5000,
                        account_id=acc1.id),
        # перевод 30к ТБанк → ВТБ (в сальдо НЕ входит)
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 15),
                        direction="transfer", op_kind="transfer", amount=30000,
                        account_id=acc1.id, transfer_account_id=acc2.id),
        # июль по alloc_date (op_date июнь, распределена на июль)
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 30),
                        alloc_date=date(2026, 7, 1),
                        direction="income", op_kind="income", amount=10000,
                        account_id=acc1.id, article_id=art_wb.id),
        # плановая — в матрицу только при include_planned
        ManualOperation(tenant_id=tenant.id, op_date=date(2026, 6, 20),
                        direction="income", op_kind="income", amount=99999,
                        is_planned=True, account_id=acc1.id, article_id=art_wb.id),
    ]
    db_session.add_all(ops)
    await db_session.flush()
    return tenant, acc1, acc2, art_wb, art_rent


async def test_matrix_sections_saldo_and_transfer(db_session, fin_tenant):
    tenant, acc1, acc2, art_wb, art_rent = fin_tenant
    m = await build_cash_flow_matrix(
        db_session, date_from=date(2026, 6, 1), date_to=date(2026, 7, 31),
    )
    assert m["months"] == ["2026-06", "2026-07"]

    # Сальдо июня: 50000 − 25000 (переводы не входят) = 25000.
    saldo_jun = next(s for s in m["saldo"] if s["month"] == "2026-06")
    assert saldo_jun["amount"] == 25000.0
    # Июль — доход по alloc_date.
    saldo_jul = next(s for s in m["saldo"] if s["month"] == "2026-07")
    assert saldo_jul["amount"] == 10000.0

    # Нераспределённый расход = 5000 в июне.
    undis = m["undistributed"]["expense"]
    assert undis["total"] == 5000.0

    # Перевод виден отдельной строкой.
    tr_jun = next(c for c in m["transfer"]["cells"] if c["month"] == "2026-06")
    assert tr_jun["amount"] == 30000.0

    # Балансы: initial 100000 + 50000 − 20000 − 5000 − 30000(из) = 95000 (ТБанк),
    # ВТБ = +30000; июльская операция тоже факт → ТБанк +10000.
    balances = await account_balances(db_session)
    by_name = {a["name"]: a["current_balance"] for a in balances["items"]}
    assert by_name["ТБанк"] == 105000.0
    assert by_name["ВТБ"] == 30000.0
    assert balances["total_balance"] == 135000.0
    # Накопленный остаток на конец июля = total (все операции учтены).
    assert m["cumulative"][-1]["amount"] == 135000.0

    # Плановая операция НЕ в матрице по умолчанию.
    inc_row = next(r for r in m["rows"] if r["label"] == "ВБ доход")
    assert inc_row["total"] == 60000.0

    m_planned = await build_cash_flow_matrix(
        db_session, date_from=date(2026, 6, 1), date_to=date(2026, 7, 31),
        include_planned=True,
    )
    inc_row_p = next(r for r in m_planned["rows"] if r["label"] == "ВБ доход")
    assert inc_row_p["total"] == 60000.0 + 99999.0


async def test_matrix_group_by_activity(db_session, fin_tenant):
    m = await build_cash_flow_matrix(
        db_session, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
        group_by="activity",
    )
    labels = {r["label"] for r in m["rows"]}
    assert "Операционная" in labels


async def test_auto_rules_fill_only_empty(db_session, fin_tenant):
    tenant, acc1, acc2, art_wb, art_rent = fin_tenant
    rule = FinanceAutoRule(
        tenant_id=tenant.id,
        name="ВБ",
        conditions=[{"field": "raw_description", "op": "contains", "value": "wildberries"}],
        actions={"article_id": art_wb.id, "official_expense": True},
    )
    db_session.add(rule)
    await db_session.flush()

    op_empty = ManualOperation(
        tenant_id=tenant.id, op_date=date(2026, 6, 21),
        direction="income", op_kind="income", amount=777,
        raw_description="Оплата от WILDBERRIES по договору",
    )
    op_categorized = ManualOperation(
        tenant_id=tenant.id, op_date=date(2026, 6, 22),
        direction="income", op_kind="income", amount=888,
        raw_description="WILDBERRIES перечисление",
        article_id=art_rent.id,  # уже категоризирована вручную
    )
    op_nomatch = ManualOperation(
        tenant_id=tenant.id, op_date=date(2026, 6, 23),
        direction="expense", op_kind="expense", amount=100,
        raw_description="Аренда офиса",
    )
    db_session.add_all([op_empty, op_categorized, op_nomatch])
    await db_session.flush()

    changed = await run_rules_on_operations(
        db_session, [op_empty, op_categorized, op_nomatch]
    )
    assert changed == 2  # op_empty (статья+флаг) и op_categorized (только флаг)
    assert op_empty.article_id == art_wb.id
    assert op_empty.official_expense is True
    assert op_empty.applied_rule_id == rule.id
    # Ручную категоризацию правило НЕ перетирает.
    assert op_categorized.article_id == art_rent.id
    assert op_categorized.official_expense is True
    assert op_nomatch.article_id is None
    assert op_nomatch.official_expense is False


async def test_backfill_invariants_after_0083(db_session):
    """Backfill 0083: у legacy-строк op_kind = direction (проверяем на живой
    БД, что нет строк с дефолтом, противоречащим direction)."""
    set_tenant(db_session, None)
    mismatched = (
        await db_session.execute(
            select(ManualOperation.id).where(
                ManualOperation.direction.in_(["income", "expense"]),
                ManualOperation.op_kind != ManualOperation.direction,
            )
        )
    ).all()
    assert mismatched == []
