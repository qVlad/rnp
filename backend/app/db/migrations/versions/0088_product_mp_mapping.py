"""product_mp_mapping — «Соответствие товаров» (TASK-DEV-094).

Маппинг own_sku (артикул своего учёта) → nm_id (карточка WB), как в TS
«Склады → Соответствие товаров».

Revision ID: 0088
Revises: 0087
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0088"
down_revision: Union[str, None] = "0087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_mp_mapping",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("own_sku", sa.String(128), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "own_sku", name="uq_product_mp_mapping"),
    )


def downgrade() -> None:
    op.drop_table("product_mp_mapping")
