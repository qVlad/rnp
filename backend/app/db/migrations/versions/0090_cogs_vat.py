"""cogs.vat_rub — НДС в себестоимости единицы (TASK-DEV-096, TS-паритет).

TS /cost ведёт себестоимость тремя колонками: себестоимость / фулфилмент /
НДС. У нас было cost+packaging+fulfillment — добавляем vat_rub (справочно,
для налоговой аналитики; в COGS-расчёт прибыли не входит, как и в TS).

Revision ID: 0090
Revises: 0089
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0090"
down_revision: Union[str, None] = "0089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cogs",
        sa.Column("vat_rub", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("cogs", "vat_rub")
