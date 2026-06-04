"""manual_operation — ручной реестр финансовых операций (Операции).

TASK-DEV-048: ручной ввод доходов/расходов (дата, сумма, статья/контрагент/счёт)
аналогично TrueStats «Финансы → Операции». Питается справочниками
finance_reference (миграция 0070).

Revision ID: 0071
Revises: 0070
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_operation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("op_date", sa.Date(), nullable=False, index=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("counterparty", sa.String(length=255), nullable=True),
        sa.Column("account", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_manual_operation_tenant_date", "manual_operation", ["tenant_id", "op_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_manual_operation_tenant_date", table_name="manual_operation")
    op.drop_table("manual_operation")
