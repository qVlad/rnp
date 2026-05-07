"""add cf_section to opex_categories with backfill

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-01 14:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Backfill mapping for default seed categories.
# Anything not listed here defaults to 'operating'.
FINANCING_NAMES = {
    "Тело кредита (погашение)",
    "Дивиденды учредителям",
    "Вложения учредителей",
    "Кредит / займ полученный",
}
INVESTING_NAMES: set[str] = set()  # no investing categories in current seed


def upgrade() -> None:
    op.add_column(
        "opex_categories",
        sa.Column("cf_section", sa.String(16), server_default="operating", nullable=False),
    )

    bind = op.get_bind()
    if FINANCING_NAMES:
        bind.execute(
            sa.text(
                "UPDATE opex_categories SET cf_section = 'financing' "
                "WHERE name = ANY(:names)"
            ),
            {"names": list(FINANCING_NAMES)},
        )
    if INVESTING_NAMES:
        bind.execute(
            sa.text(
                "UPDATE opex_categories SET cf_section = 'investing' "
                "WHERE name = ANY(:names)"
            ),
            {"names": list(INVESTING_NAMES)},
        )


def downgrade() -> None:
    op.drop_column("opex_categories", "cf_section")
