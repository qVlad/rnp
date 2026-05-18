"""external_ad_costs.brand — атрибутирование расхода на конкретный бренд

ROADMAP P1. До сих пор у `external_ad_costs` было два уровня:
- `nm_id NOT NULL` — конкретная SKU; идёт точно в её юнит-экономику.
- `nm_id IS NULL` — "бренд-уровень" — но реально никак не привязано к
  бренду. В юнит-экономике распределялось pro-rata по выручке всех видимых
  SKU. Для manager-scope такие строки просто отбрасывались.

Проблемы:
- Если директор завёл "блогер для PRO" с nm_id=NULL, manager бренда PRO
  не видел этот расход → DRR заниженный → ошибочные решения.
- Манагеру бренда A могли проп-рейту привязать расход бренда B (т.к.
  бренд не был привязан).

Решение: добавить колонку `brand: VARCHAR(128) | NULL`. Трёхуровневая
атрибуция:
1. nm_id NOT NULL  → SKU-level (как было).
2. nm_id IS NULL, brand IS NOT NULL → brand-level. Распределяется
   pro-rata по выручке SKU **внутри** этого бренда. Manager видит, если
   бренд в его assignments.
3. nm_id IS NULL, brand IS NULL → company-wide. Распределяется pro-rata
   по всем видимым SKU. Manager НЕ видит (только director / head).

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-18 00:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "external_ad_costs",
        sa.Column("brand", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_external_ad_costs_brand", "external_ad_costs", ["brand"]
    )


def downgrade() -> None:
    op.drop_index("ix_external_ad_costs_brand", table_name="external_ad_costs")
    op.drop_column("external_ad_costs", "brand")
