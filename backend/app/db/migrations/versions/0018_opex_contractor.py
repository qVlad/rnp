"""opex_entries: add `contractor` column.

Контрагент / подрядчик для статьи расхода — нужен чтобы видеть «куда уходят
деньги»: оплата конкретному агентству, ИП-исполнителю, блогеру и т.п. Поле
свободное (String, nullable) — без справочника контрагентов на этом этапе.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-14 17:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "opex_entries",
        sa.Column("contractor", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("opex_entries", "contractor")
