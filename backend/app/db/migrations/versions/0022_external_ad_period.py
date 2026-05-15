"""external_ad_costs: add `end_date` for period-based spend distribution.

10X-методика: если рекламная кампания идёт несколько дней (блогер выложил
рилс который продвигает товар неделю), сумма расхода распределяется
равномерно по дням [start..end]. Без end_date сумма считается точечной (то
же что spend_date = end_date — обратно совместимо).

Колонка nullable: legacy записи с end_date=NULL обрабатываются как точечные.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-15 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "external_ad_costs",
        sa.Column("end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_ad_costs", "end_date")
