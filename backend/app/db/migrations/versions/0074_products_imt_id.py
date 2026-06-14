"""products.imt_id — WB склейка (imtID из Content API).

TASK-DEV-082 (TS-parity «Синхронизация склеек»): карточки с одинаковым imtID =
одна склейка WB. Авто-группировка /product-groups создаёт группу на склейку.

Revision ID: 0074
Revises: 0073
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0074"
down_revision: Union[str, None] = "0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("imt_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_products_imt_id", "products", ["imt_id"])


def downgrade() -> None:
    op.drop_index("ix_products_imt_id", table_name="products")
    op.drop_column("products", "imt_id")
