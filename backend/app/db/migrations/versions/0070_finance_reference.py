"""finance_reference — справочники для операций/ДДС (Дополнительно).

TASK-DEV-043: свои статьи расходов / контрагенты / счета для быстрого выбора
при внесении операций (аналог TrueStats «Финансы → Дополнительно»).

Revision ID: 0070
Revises: 0069
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0070"
down_revision: Union[str, None] = "0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_reference",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("ref_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_finance_reference_tenant_type",
        "finance_reference",
        ["tenant_id", "ref_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_finance_reference_tenant_type", table_name="finance_reference")
    op.drop_table("finance_reference")
