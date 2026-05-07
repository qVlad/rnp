"""Add new WB reportDetailByPeriod fields (2025-2026 API additions)

Adds to wb_report_detail:
  - retail_price_withdisc_rub  actual buyer price post-discount/SPP
  - kiz                        marking code (Честный знак)
  - ppvz_vw                    WB commission pre-VAT
  - ppvz_vw_nds                WB commission VAT amount
  - supplier_reward            net seller reward (post-tax)

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-30 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_report_detail",
        sa.Column("retail_price_withdisc_rub", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "wb_report_detail",
        sa.Column("kiz", sa.String(128), nullable=True),
    )
    op.add_column(
        "wb_report_detail",
        sa.Column("ppvz_vw", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "wb_report_detail",
        sa.Column("ppvz_vw_nds", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "wb_report_detail",
        sa.Column("supplier_reward", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wb_report_detail", "supplier_reward")
    op.drop_column("wb_report_detail", "ppvz_vw_nds")
    op.drop_column("wb_report_detail", "ppvz_vw")
    op.drop_column("wb_report_detail", "kiz")
    op.drop_column("wb_report_detail", "retail_price_withdisc_rub")
