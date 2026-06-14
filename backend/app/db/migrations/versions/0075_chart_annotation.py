"""chart_annotation — команд-аннотации на дату (маркеры на графиках).

TASK-DEV-081 (TS-parity «комментарии-маркеры»): заметка, привязанная к дате,
рисуется ReferenceLine на timeseries и видна всей команде.

Revision ID: 0075
Revises: 0074
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0075"
down_revision: Union[str, None] = "0074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chart_annotation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("dt", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chart_annotation_tenant_dt", "chart_annotation", ["tenant_id", "dt"]
    )


def downgrade() -> None:
    op.drop_index("ix_chart_annotation_tenant_dt", table_name="chart_annotation")
    op.drop_table("chart_annotation")
