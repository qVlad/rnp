"""finance_auto_rule — автоправила категоризации операций (TASK-DEV-093).

Условия (AND) → действия (статья/контрагент/официальный расход).
Прогон при импорте выписки + «применить к существующим».

Revision ID: 0085
Revises: 0084
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0085"
down_revision: Union[str, None] = "0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_auto_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("conditions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("actions", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_finance_auto_rule_tenant", "finance_auto_rule", ["tenant_id"])
    op.create_foreign_key(
        "fk_manual_operation_applied_rule",
        "manual_operation",
        "finance_auto_rule",
        ["applied_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manual_operation_applied_rule", "manual_operation", type_="foreignkey"
    )
    op.drop_index("ix_finance_auto_rule_tenant", table_name="finance_auto_rule")
    op.drop_table("finance_auto_rule")
