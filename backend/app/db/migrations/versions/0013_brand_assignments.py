"""brand assignments + head_of_sales role

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-07 18:00:00

`users.role` is already a free-form VARCHAR(16) and accepts any string, so no
schema change is needed — `head_of_sales` is just a new value the application
recognises.

The new `brand_assignments` table maps WB brands to a responsible manager
(1:1, UNIQUE(brand)). Director and head_of_sales can edit assignments;
managers see only nm_ids belonging to their assigned brands across the app.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("brand", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_brand_assignments_user_id", "brand_assignments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_brand_assignments_user_id", table_name="brand_assignments")
    op.drop_table("brand_assignments")
