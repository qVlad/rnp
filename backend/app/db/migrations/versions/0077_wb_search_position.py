"""wb_search_position — полная выдача поиска WB (наши + конкуренты).

TASK-DEV-085 follow-up (конкурентное сравнение в Джеме): расширение шлёт весь
видимый ранг для запросов, где есть наша карточка. is_own ставится на бэке.

Revision ID: 0077
Revises: 0076
Create Date: 2026-06-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0077"
down_revision: Union[str, None] = "0076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_search_position",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_own", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
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
        "ix_wb_search_pos_tenant_q_dt",
        "wb_search_position",
        ["tenant_id", "query", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wb_search_pos_tenant_q_dt", table_name="wb_search_position")
    op.drop_table("wb_search_position")
