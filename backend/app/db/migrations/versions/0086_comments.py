"""comments — комментарии-треды на сущностях (TASK-DEV-094, TS-паритет).

entity_type (kpi|sku|warehouse|rnp_row|plan|report) + entity_key → тред.
Счётчики 💬 на KPI-плитках, колонка «Комментарии» у артикулов.

Revision ID: 0086
Revises: 0085
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0086"
down_revision: Union[str, None] = "0085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_key", sa.String(128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_comments_entity", "comments", ["tenant_id", "entity_type", "entity_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_comments_entity", table_name="comments")
    op.drop_table("comments")
