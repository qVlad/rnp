"""WB tariff categories with seed data

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-01 16:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed: (name, commission_pct, logistics_per_unit_rub, sort_order)
# Numbers are approximate, current as of Q1 2026 for FBO. Real rates depend on
# exact subcategory and may change — calculator allows inline override.
SEED: list[tuple[str, float, float, int]] = [
    ("Универсальная (по умолчанию)",         18.0,  80, 0),
    ("Одежда и обувь",                        23.0, 130, 10),
    ("Электроника",                           17.0, 110, 20),
    ("Бытовая техника",                       15.0, 250, 30),
    ("Косметика и парфюмерия",                18.0,  60, 40),
    ("Здоровье и БАД",                        18.0,  50, 50),
    ("Продукты питания",                       7.0,  60, 60),
    ("Бытовая химия",                         12.0,  70, 70),
    ("Игрушки и детские товары",              17.0,  90, 80),
    ("Дом и кухня",                           15.0, 100, 90),
    ("Спорт и фитнес",                        18.0, 120, 100),
    ("Авто-аксессуары",                       17.0, 100, 110),
    ("Зоотовары",                             15.0,  80, 120),
    ("Канцтовары и книги",                     7.0,  60, 130),
    ("Сад и огород",                          15.0, 130, 140),
    ("Ювелирные изделия",                     25.0,  60, 150),
]


def upgrade() -> None:
    op.create_table(
        "wb_tariff_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("commission_pct", sa.Numeric(5, 2), server_default="18"),
        sa.Column("default_logistics_per_unit", sa.Numeric(8, 2), server_default="80"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
    )

    bind = op.get_bind()
    for name, commission, logistics, order in SEED:
        bind.execute(
            sa.text(
                "INSERT INTO wb_tariff_categories "
                "(name, commission_pct, default_logistics_per_unit, sort_order) "
                "VALUES (:name, :c, :l, :o)"
            ),
            {"name": name, "c": commission, "l": logistics, "o": order},
        )


def downgrade() -> None:
    op.drop_table("wb_tariff_categories")
