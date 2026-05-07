"""archive flag for products

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-01 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("products", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("products", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.create_index("ix_products_is_archived", "products", ["is_archived"])


def downgrade() -> None:
    op.drop_index("ix_products_is_archived", table_name="products")
    op.drop_column("products", "last_seen_at")
    op.drop_column("products", "archived_at")
    op.drop_column("products", "is_archived")
