"""wb_card_price — реальная витринная цена покупателя с СПП.

TASK-DEV-037 ph3: СПП в seller-API нет. Тянем реальную цену покупателя из
публичного card.wb.ru/cards/v4 (без токена) и храним per-tenant per-nm, чтобы
/unit-plan показывал реальный СПП вместо ручного spp_default_pct.

Revision ID: 0069
Revises: 0068
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_card_price",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("basic_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("buyer_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("observed_spp_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "dest", sa.BigInteger(), nullable=False, server_default=sa.text("123585712")
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "nm_id", name="pk_wb_card_price"),
    )


def downgrade() -> None:
    op.drop_table("wb_card_price")
