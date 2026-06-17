"""unit_plan_global_config: ручной override комиссии + скидка комиссии (DEV-089).

Запрос пользователя 2026-06-17: тариф комиссии WB Tariffs для категории неверный
(38% вместо 34.5%), плюс есть опции продавца, возвращающие 0.75% → нужная
комиссия 33.75%. Добавляем:
  commission_override_pct — заменяет тариф, когда задан (NULL → тариф);
  commission_discount_pct — вычитается из комиссии (опции, напр. 0.75%).

Revision ID: 0079
Revises: 0078
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0079"
down_revision: Union[str, None] = "0078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "unit_plan_global_config",
        sa.Column("commission_override_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "unit_plan_global_config",
        sa.Column("commission_discount_pct", sa.Numeric(5, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("unit_plan_global_config", "commission_discount_pct")
    op.drop_column("unit_plan_global_config", "commission_override_pct")
