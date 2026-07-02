"""finance_import_batch — журнал импортов банковских выписок (TASK-DEV-093).

Файл (1С 1CClientBankExchange / Excel / CSV) → preview/needs_mapping →
commit → операции source='import'. payload хранит распарсенные строки
между preview и commit (обнуляется после импорта).

Revision ID: 0084
Revises: 0083
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0084"
down_revision: Union[str, None] = "0083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_import_batch",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("finance_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("mapping", JSONB(), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("imported_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_finance_import_batch_tenant", "finance_import_batch", ["tenant_id"]
    )
    op.create_foreign_key(
        "fk_manual_operation_import_batch",
        "manual_operation",
        "finance_import_batch",
        ["import_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manual_operation_import_batch", "manual_operation", type_="foreignkey"
    )
    op.drop_index("ix_finance_import_batch_tenant", table_name="finance_import_batch")
    op.drop_table("finance_import_batch")
