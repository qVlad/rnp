"""wb_funnel_daily.cancel_count — отмены из Воронки для корректного % выкупа.

Запрос пользователя 2026-06-15: % выкупа на /unit-plan должен совпадать с
Воронкой WB. WB «% выкупа» = buyouts/(buyouts+cancels), знаменатель —
терминальные заказы (без «в пути»). Нужен cancelCount.

Revision ID: 0078
Revises: 0077
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0078"
down_revision: Union[str, None] = "0077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_funnel_daily", sa.Column("cancel_count", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("wb_funnel_daily", "cancel_count")
