"""Финансы TS-стиль, часть 1 (TASK-DEV-093): finance_account + эволюция
manual_operation в универсальную банковскую операцию.

- finance_account: счета с начальным балансом (текущий вычисляется).
- manual_operation: op_kind (income|expense|transfer), alloc_date (дата
  распределения для ДДС), FK на счета/статьи/контрагентов, official_expense,
  source (manual|import|auto_plan), поля импорта (raw_description, doc_number,
  dedup_hash, import_batch_id — FK добавит 0084, applied_rule_id — 0085).
- Backfill (данные НЕ теряем, только дополняем):
  1) distinct manual_operation.account (+ finance_reference ref_type=account)
     → finance_account, проставить account_id по имени;
  2) distinct category/counterparty → недостающие finance_reference,
     проставить article_id/counterparty_id;
  3) extra.op_type/activity дефолты на статьях;
  4) op_kind = direction.

Revision ID: 0083
Revises: 0082
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0083"
down_revision: Union[str, None] = "0082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_account",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "initial_balance", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("initial_balance_date", sa.Date(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bank_meta", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_finance_account_name"),
    )
    op.create_index("ix_finance_account_tenant", "finance_account", ["tenant_id"])

    op.add_column(
        "manual_operation",
        sa.Column("op_kind", sa.String(16), nullable=False, server_default="expense"),
    )
    op.add_column("manual_operation", sa.Column("alloc_date", sa.Date(), nullable=True))
    op.add_column(
        "manual_operation",
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("finance_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "manual_operation",
        sa.Column(
            "transfer_account_id",
            sa.Integer(),
            sa.ForeignKey("finance_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "manual_operation",
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("finance_reference.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "manual_operation",
        sa.Column(
            "counterparty_id",
            sa.Integer(),
            sa.ForeignKey("finance_reference.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "manual_operation",
        sa.Column(
            "official_expense", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "manual_operation",
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column(
        "manual_operation", sa.Column("import_batch_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "manual_operation", sa.Column("raw_description", sa.Text(), nullable=True)
    )
    op.add_column(
        "manual_operation", sa.Column("doc_number", sa.String(64), nullable=True)
    )
    op.add_column(
        "manual_operation", sa.Column("dedup_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "manual_operation", sa.Column("applied_rule_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_manual_operation_tenant_date", "manual_operation", ["tenant_id", "op_date"]
    )
    op.create_index(
        "ix_manual_operation_tenant_account",
        "manual_operation",
        ["tenant_id", "account_id"],
    )
    # Дедуп импорта: один и тот же платёж из выписки не задваивается при
    # повторной загрузке файла. Только для source='import' — ручные операции
    # не ограничиваем (легитимные одинаковые записи).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_manual_operation_import_dedup
        ON manual_operation (tenant_id, dedup_hash)
        WHERE source = 'import' AND dedup_hash IS NOT NULL
        """
    )

    # ── Backfill ──────────────────────────────────────────────────────────
    # 1) op_kind = direction (у legacy-строк direction ∈ income|expense).
    op.execute(
        "UPDATE manual_operation SET op_kind = direction "
        "WHERE direction IN ('income', 'expense')"
    )

    # 2) Счета: distinct имена из операций + справочника finance_reference.
    op.execute(
        """
        INSERT INTO finance_account (tenant_id, name)
        SELECT DISTINCT tenant_id, trim(account)
        FROM manual_operation
        WHERE account IS NOT NULL AND trim(account) <> ''
        ON CONFLICT (tenant_id, name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO finance_account (tenant_id, name)
        SELECT DISTINCT tenant_id, trim(name)
        FROM finance_reference
        WHERE ref_type = 'account' AND trim(name) <> ''
        ON CONFLICT (tenant_id, name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE manual_operation mo
        SET account_id = fa.id
        FROM finance_account fa
        WHERE mo.account_id IS NULL
          AND mo.account IS NOT NULL
          AND fa.tenant_id = mo.tenant_id
          AND fa.name = trim(mo.account)
        """
    )

    # 3) Статьи: distinct category → finance_reference(expense_category).
    #    Дубли имён в справочнике возможны — берём МИНИМАЛЬНЫЙ id на имя.
    op.execute(
        """
        INSERT INTO finance_reference (tenant_id, ref_type, name)
        SELECT DISTINCT mo.tenant_id, 'expense_category', trim(mo.category)
        FROM manual_operation mo
        WHERE mo.category IS NOT NULL AND trim(mo.category) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM finance_reference fr
            WHERE fr.tenant_id = mo.tenant_id
              AND fr.ref_type = 'expense_category'
              AND fr.name = trim(mo.category)
          )
        """
    )
    op.execute(
        """
        UPDATE manual_operation mo
        SET article_id = fr.min_id
        FROM (
            SELECT tenant_id, name, min(id) AS min_id
            FROM finance_reference WHERE ref_type = 'expense_category'
            GROUP BY tenant_id, name
        ) fr
        WHERE mo.article_id IS NULL
          AND mo.category IS NOT NULL
          AND fr.tenant_id = mo.tenant_id
          AND fr.name = trim(mo.category)
        """
    )

    # 4) Контрагенты — аналогично.
    op.execute(
        """
        INSERT INTO finance_reference (tenant_id, ref_type, name)
        SELECT DISTINCT mo.tenant_id, 'counterparty', trim(mo.counterparty)
        FROM manual_operation mo
        WHERE mo.counterparty IS NOT NULL AND trim(mo.counterparty) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM finance_reference fr
            WHERE fr.tenant_id = mo.tenant_id
              AND fr.ref_type = 'counterparty'
              AND fr.name = trim(mo.counterparty)
          )
        """
    )
    op.execute(
        """
        UPDATE manual_operation mo
        SET counterparty_id = fr.min_id
        FROM (
            SELECT tenant_id, name, min(id) AS min_id
            FROM finance_reference WHERE ref_type = 'counterparty'
            GROUP BY tenant_id, name
        ) fr
        WHERE mo.counterparty_id IS NULL
          AND mo.counterparty IS NOT NULL
          AND fr.tenant_id = mo.tenant_id
          AND fr.name = trim(mo.counterparty)
        """
    )

    # 5) Дефолты типа/вида деятельности на статьях (extra JSONB).
    #    Статья, встречающаяся у income-операций — op_type='income'.
    op.execute(
        """
        UPDATE finance_reference fr
        SET extra = coalesce(fr.extra, '{}'::jsonb)
                    || jsonb_build_object(
                        'op_type',
                        CASE WHEN EXISTS (
                          SELECT 1 FROM manual_operation mo
                          WHERE mo.article_id = fr.id AND mo.direction = 'income'
                        ) THEN 'income' ELSE 'expense' END,
                        'activity', 'operating')
        WHERE fr.ref_type = 'expense_category'
          AND (fr.extra IS NULL OR NOT fr.extra ? 'op_type')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_manual_operation_import_dedup")
    op.drop_index("ix_manual_operation_tenant_account", table_name="manual_operation")
    op.drop_index("ix_manual_operation_tenant_date", table_name="manual_operation")
    for col in (
        "applied_rule_id", "dedup_hash", "doc_number", "raw_description",
        "import_batch_id", "source", "official_expense", "counterparty_id",
        "article_id", "transfer_account_id", "account_id", "alloc_date", "op_kind",
    ):
        op.drop_column("manual_operation", col)
    op.drop_index("ix_finance_account_tenant", table_name="finance_account")
    op.drop_table("finance_account")
