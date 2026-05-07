"""sales plans (План-Факт)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-01 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(16), server_default="store", nullable=False),
        sa.Column("scope_id", sa.BigInteger()),
        sa.Column("planned_orders_qty", sa.Integer(), server_default="0"),
        sa.Column("planned_orders_revenue", sa.Numeric(14, 2), server_default="0"),
        sa.Column("planned_sales_qty", sa.Integer(), server_default="0"),
        sa.Column("planned_sales_revenue", sa.Numeric(14, 2), server_default="0"),
        sa.Column("planned_profit", sa.Numeric(14, 2), server_default="0"),
        sa.Column("planned_marketing_cost", sa.Numeric(14, 2), server_default="0"),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sales_plans_period_year", "sales_plans", ["period_year"])
    op.create_index("ix_sales_plans_period_month", "sales_plans", ["period_month"])
    op.create_index(
        "uq_sales_plans_period_scope",
        "sales_plans",
        ["period_year", "period_month", "scope_type", "scope_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_sales_plans_period_scope", table_name="sales_plans")
    op.drop_index("ix_sales_plans_period_month", table_name="sales_plans")
    op.drop_index("ix_sales_plans_period_year", table_name="sales_plans")
    op.drop_table("sales_plans")
