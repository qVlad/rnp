"""UNIT_PLAN.md §14.5: reverse_logistics_mode в unit_plan_global_config.

Excel-эталон содержит противоречие в формуле AF (логистика weighted-avg):
- row 3 использует `(AD×Z + (1-AD)×(Z+AG))/AD` с volume-зависимым AG
- rows 4+ используют фиксированное `(AD×Z + (1-AD)×(Z+50))/AD`

Делаем выбор настраиваемым через флаг в global_config:
- 'tariff'  — методически правильно, AG из WB-тарифа короба (default)
- 'flat_50' — фиксированная 50₽, как в большинстве строк Excel-эталона

Revision ID: 0046
Revises: 0045
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "unit_plan_global_config",
        sa.Column(
            "reverse_logistics_mode",
            sa.String(16),
            nullable=False,
            server_default="tariff",
        ),
    )


def downgrade() -> None:
    op.drop_column("unit_plan_global_config", "reverse_logistics_mode")
