"""box_distribution_src.distributed_qty — трекинг частичной раскладки (DEV-091).

Чтобы нельзя было распределить короб дважды и показывать остатки при частичной
раскладке: distributed_qty = сколько из qty этой строки уже разложено.

Revision ID: 0081
Revises: 0080
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0081"
down_revision: Union[str, None] = "0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "box_distribution_src",
        sa.Column(
            "distributed_qty",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("box_distribution_src", "distributed_qty")
