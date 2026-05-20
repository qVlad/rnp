"""metric_templates — пользовательские формулы для kастомных KPI (TASK-DEV-011).

TrueStats умеет — мы догоняем. Пользователь пишет формулу вроде
`(revenue_net - ad_cost) / orders` с whitelisted переменными KPI и
видит результат на Dashboard рядом со стандартными KPI.

Эвалюатор — `simpleeval` с whitelisting (только арифметика + abs/min/max/round).
Не SQL injection-safe для произвольного SQL — но мы и не строим SQL.

Revision ID: 0050
Revises: 0049
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        # Формат вывода: 'currency' / 'percent' / 'number'
        sa.Column("format", sa.String(16), nullable=False, server_default="number"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_metric_templates_tenant_name"),
    )
    op.create_index(
        "ix_metric_templates_tenant", "metric_templates", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_metric_templates_tenant", table_name="metric_templates")
    op.drop_table("metric_templates")
