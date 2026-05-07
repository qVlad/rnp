"""finance model 'real': artificial orders, external ad costs, OPEX

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-30 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default OPEX categories — 28 expense types + 3 income types, mirrored from
# the convention used by mpfact / rask. is_fixed and in_operating are tuned
# so that out-of-the-box the P&L "operating profit" line is sane.
OPEX_SEED: list[tuple[str, str, bool, bool]] = [
    # name, kind, is_fixed, in_operating
    # === fixed expenses (постоянные, попадают в опер.прибыль) ===
    ("Заработная плата", "expense", True, True),
    ("Подрядчики (постоянные)", "expense", True, True),
    ("Аренда офиса", "expense", True, True),
    ("Аренда склада", "expense", True, True),
    ("Бухгалтерия / аудит", "expense", True, True),
    ("Связь и интернет", "expense", True, True),
    ("Хостинг и SaaS-подписки", "expense", True, True),
    ("Юр.услуги", "expense", True, True),
    ("Обучение / коучинг", "expense", True, True),
    ("Командировки", "expense", True, True),
    ("Канцелярия и хоз.расходы", "expense", True, True),
    ("Страхование", "expense", True, True),
    # === variable expenses (переменные, попадают в опер.прибыль) ===
    ("Подрядчики (разовые)", "expense", False, True),
    ("Логистика собственная", "expense", False, True),
    ("Упаковка", "expense", False, True),
    ("Маркетинг внешний (банки, посевы)", "expense", False, True),
    ("Возвраты подрядчикам", "expense", False, True),
    ("Курьерские услуги", "expense", False, True),
    ("Сертификация / тестирование", "expense", False, True),
    ("Комиссия эквайринга вне WB", "expense", False, True),
    ("Закупка тары", "expense", False, True),
    ("Прочие переменные", "expense", False, True),
    # === expenses that bypass operating profit, only in cash flow (ДДС) ===
    ("Налог на прибыль / УСН", "expense", False, False),
    ("НДС к уплате", "expense", False, False),
    ("Страховые взносы", "expense", True, False),
    ("Тело кредита (погашение)", "expense", False, False),
    ("Проценты по кредиту", "expense", False, True),
    ("Дивиденды учредителям", "expense", False, False),
    # === income (только в ДДС, не в опер.прибыль) ===
    ("Вложения учредителей", "income", False, False),
    ("Кредит / займ полученный", "income", False, False),
    ("Прочие поступления", "income", False, False),
]


def upgrade() -> None:
    op.create_table(
        "artificial_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("order_dt", sa.Date(), nullable=False),
        sa.Column("completion_dt", sa.Date()),
        sa.Column("nm_id", sa.BigInteger()),
        sa.Column("qty", sa.Integer(), server_default="1"),
        sa.Column("gross_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("contractor_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_artificial_orders_type", "artificial_orders", ["type"])
    op.create_index("ix_artificial_orders_order_dt", "artificial_orders", ["order_dt"])
    op.create_index("ix_artificial_orders_nm_id", "artificial_orders", ["nm_id"])

    op.create_table(
        "external_ad_costs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("spend_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger()),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_external_ad_costs_spend_date", "external_ad_costs", ["spend_date"])
    op.create_index("ix_external_ad_costs_nm_id", "external_ad_costs", ["nm_id"])

    op.create_table(
        "opex_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), server_default="expense"),
        sa.Column("is_fixed", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("in_operating", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "opex_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("opex_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_opex_entries_entry_date", "opex_entries", ["entry_date"])
    op.create_index("ix_opex_entries_category_id", "opex_entries", ["category_id"])

    # Seed default OPEX categories.
    bind = op.get_bind()
    for name, kind, is_fixed, in_operating in OPEX_SEED:
        bind.execute(
            sa.text(
                "INSERT INTO opex_categories (name, kind, is_fixed, in_operating, is_default) "
                "VALUES (:name, :kind, :is_fixed, :in_operating, true)"
            ),
            {"name": name, "kind": kind, "is_fixed": is_fixed, "in_operating": in_operating},
        )


def downgrade() -> None:
    op.drop_index("ix_opex_entries_category_id", table_name="opex_entries")
    op.drop_index("ix_opex_entries_entry_date", table_name="opex_entries")
    op.drop_table("opex_entries")
    op.drop_table("opex_categories")
    op.drop_index("ix_external_ad_costs_nm_id", table_name="external_ad_costs")
    op.drop_index("ix_external_ad_costs_spend_date", table_name="external_ad_costs")
    op.drop_table("external_ad_costs")
    op.drop_index("ix_artificial_orders_nm_id", table_name="artificial_orders")
    op.drop_index("ix_artificial_orders_order_dt", table_name="artificial_orders")
    op.drop_index("ix_artificial_orders_type", table_name="artificial_orders")
    op.drop_table("artificial_orders")
