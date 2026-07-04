"""wb_sync_revision + wb_sync_change — ревизии WB-отчётов (TASK-DEV-095).

Переподгрузка исторических отчётов WB с версионированием: основная таблица
держит актуальные данные, прежние значения изменённых строк и отклонённые
FREEZE-обновления — в журнале изменений.

Revision ID: 0089
Revises: 0088
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0089"
down_revision: Union[str, None] = "0088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_sync_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source", sa.String(32), nullable=False, index=True),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("rows_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("totals_delta", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(16), nullable=False, server_default="beat"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "wb_sync_change",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "revision_id",
            sa.BigInteger(),
            sa.ForeignKey("wb_sync_revision.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("entity_key", sa.String(128), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("old", JSONB(), nullable=True),
        sa.Column("new", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_wb_sync_change_entity", "wb_sync_change", ["tenant_id", "entity_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_wb_sync_change_entity", table_name="wb_sync_change")
    op.drop_table("wb_sync_change")
    op.drop_table("wb_sync_revision")
