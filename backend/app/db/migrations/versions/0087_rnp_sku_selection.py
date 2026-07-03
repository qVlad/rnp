"""rnp_sku_selection — выбор артикулов для модуля РНП (TASK-DEV-094).

Аналог TrueStats «Настройки РНП»: toggle per SKU. Нет строк = показывать все.

Revision ID: 0087
Revises: 0086
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0087"
down_revision: Union[str, None] = "0086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rnp_sku_selection",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "nm_id", name="uq_rnp_sku_selection"),
    )


def downgrade() -> None:
    op.drop_table("rnp_sku_selection")
