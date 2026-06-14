"""off_platform_stock_movements.warehouse_name — мульти-склад (свои склады).

TASK-DEV-083 (TS-parity «Склады»): несколько своих складов + перемещения между
ними. NULL = «Основной» (back-compat для существующих движений).

Revision ID: 0076
Revises: 0075
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0076"
down_revision: Union[str, None] = "0075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "off_platform_stock_movements",
        sa.Column("warehouse_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_off_platform_warehouse",
        "off_platform_stock_movements",
        ["warehouse_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_off_platform_warehouse", table_name="off_platform_stock_movements"
    )
    op.drop_column("off_platform_stock_movements", "warehouse_name")
