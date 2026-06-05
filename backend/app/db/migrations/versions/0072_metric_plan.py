"""metric_plan + metric_plan_target — План-факт по метрикам (копия TrueStats).

TASK-DEV-050: план = период + целевые метрики; факт считается из наших данных.

Revision ID: 0072
Revises: 0071
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0072"
down_revision: Union[str, None] = "0071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_plan",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("finished_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "metric_plan_target",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("metric_plan.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("metric_slug", sa.String(length=64), nullable=False),
        sa.Column("plan_value", sa.Numeric(16, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("metric_plan_target")
    op.drop_table("metric_plan")
