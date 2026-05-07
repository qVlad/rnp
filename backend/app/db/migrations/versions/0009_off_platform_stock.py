"""off-platform stock movements (capitalization)

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-02 03:35:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "off_platform_stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dt", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "unit_cost",
            sa.Numeric(12, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_off_platform_stock_dt", "off_platform_stock_movements", ["dt"])
    op.create_index(
        "ix_off_platform_stock_nm_id", "off_platform_stock_movements", ["nm_id"]
    )
    op.create_index("ix_off_platform_stock_kind", "off_platform_stock_movements", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_off_platform_stock_kind", table_name="off_platform_stock_movements")
    op.drop_index("ix_off_platform_stock_nm_id", table_name="off_platform_stock_movements")
    op.drop_index("ix_off_platform_stock_dt", table_name="off_platform_stock_movements")
    op.drop_table("off_platform_stock_movements")
