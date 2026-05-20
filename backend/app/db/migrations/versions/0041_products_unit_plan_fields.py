"""UNIT-PLAN Sprint 1 Lane A: расширение `products` плановыми полями.

`volume_l` — объём карточки в литрах (используется в формулах логистики /
хранения / приёмки). Заполняется через UI или импорт XLSX из «UNIT-плана».

`warehouse_default` — склад по умолчанию (если override.warehouse_name пуст,
используется этот). Из products можно подсасывать например первый склад из
wb_stocks с ненулевым остатком.

`is_monopallet` / `items_per_monopallet` — поставка монопаллетой, переключает
формулу логистики (см. UNIT_PLAN.md §4 формула B).

См. `UNIT_PLAN.md` §3 (DDL), §4 (формулы Z/AC/AI).

Revision ID: 0041
Revises: 0040
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "volume_l",
            sa.Numeric(8, 3),
            nullable=True,
            comment="Объём карточки в литрах (для формул логистики / хранения / приёмки)",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "warehouse_default",
            sa.String(255),
            nullable=True,
            comment="Склад по умолчанию (fallback если override.warehouse_name пуст)",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "is_monopallet",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Поставка монопаллетой (переключает формулу логистики)",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "items_per_monopallet",
            sa.Integer(),
            nullable=True,
            comment="Сколько единиц SKU умещается в одной монопаллете",
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "items_per_monopallet")
    op.drop_column("products", "is_monopallet")
    op.drop_column("products", "warehouse_default")
    op.drop_column("products", "volume_l")
