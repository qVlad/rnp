"""future-dated tax/VAT parameter timeline

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-01 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setting_timeline",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_setting_timeline_key", "setting_timeline", ["key"])
    op.create_index("ix_setting_timeline_effective_from", "setting_timeline", ["effective_from"])
    op.create_index(
        "uq_setting_timeline_key_date",
        "setting_timeline",
        ["key", "effective_from"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_setting_timeline_key_date", table_name="setting_timeline")
    op.drop_index("ix_setting_timeline_effective_from", table_name="setting_timeline")
    op.drop_index("ix_setting_timeline_key", table_name="setting_timeline")
    op.drop_table("setting_timeline")
