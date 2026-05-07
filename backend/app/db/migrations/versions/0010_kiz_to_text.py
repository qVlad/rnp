"""widen wb_report_detail.kiz to TEXT (was varchar(128) — WB can return longer)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-04 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "wb_report_detail",
        "kiz",
        type_=sa.Text(),
        existing_type=sa.String(128),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "wb_report_detail",
        "kiz",
        type_=sa.String(128),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
