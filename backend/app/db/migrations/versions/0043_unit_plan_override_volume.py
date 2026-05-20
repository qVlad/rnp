"""UNIT-PLAN-013: добавляем `volume_l` в `unit_plan_override`.

Зачем: paste-from-Excel для столбца «Литры» на странице `/unit-plan` должен
бить в override, а не в `products.volume_l` — это позволяет менеджеру править
литры своих SKU не трогая основную карточку товара (которая обновляется sync'ом
из WB content-API). Loader выбирает effective volume как `override.volume_l ??
product.volume_l`.

Revision ID: 0043
Revises: 0042
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "unit_plan_override",
        sa.Column("volume_l", sa.Numeric(8, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("unit_plan_override", "volume_l")
