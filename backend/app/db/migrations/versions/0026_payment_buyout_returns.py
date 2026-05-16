"""wb_payment_order.buyout_returns_amount — возвраты выкупов из Стас xlsx
(колонка AA «Возвраты выкупы»).

Используется в `services/tax_report_usn.py` для расчёта УСН 6% (Доходы):
методика бухгалтера включает возвраты выкупов в налоговую базу,
бакетированные по `period_end` месяца отчёта «По выкупам».

В АУСН-методике этот компонент справочный (формула B6 включает в SUM
но через `-B6` обнуляется).

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-15 19:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "buyout_returns_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("wb_payment_order", "buyout_returns_amount")
