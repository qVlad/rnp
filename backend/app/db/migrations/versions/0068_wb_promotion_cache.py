"""wb_promotion + wb_promotion_nomenclature — кэш акций WB-календаря.

TASK-DEV-037: раньше /promo-calculator-wb дёргал WB при каждом заходе
(list promotions + details по каждой акции + nomenclatures по клику) — главный
источник лишних обращений к WB. Теперь акции синкаются раз в день
(sync/tasks_promotions.py, beat 08:30 MSK) и UI читает из БД.

- wb_promotion: список акций + агрегаты (счётчики, ranging-бустинг, raw details).
- wb_promotion_nomenclature: товары акции с ценами. source='wb' (публичный API)
  или 'excel' (загруженный Excel автоакции — TASK-DEV-035).

Revision ID: 0068
Revises: 0067
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_promotion",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("start_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promo_type", sa.String(length=32), nullable=True),
        sa.Column("in_promo_count", sa.Integer(), nullable=True),
        sa.Column("not_in_promo_count", sa.Integer(), nullable=True),
        sa.Column("products_count", sa.Integer(), nullable=True),
        sa.Column("in_promo_action", sa.Boolean(), nullable=True),
        sa.Column("ranging", JSONB(), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wb_promotion"),
        sa.UniqueConstraint(
            "tenant_id", "promotion_id", name="uq_wb_promotion_tenant_promo"
        ),
    )
    op.create_index(
        "ix_wb_promotion_tenant_id", "wb_promotion", ["tenant_id"], unique=False
    )

    op.create_table(
        "wb_promotion_nomenclature",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "in_action", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("promo_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("plan_discount_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "source", sa.String(length=16), nullable=False, server_default=sa.text("'wb'")
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wb_promotion_nomenclature"),
        sa.UniqueConstraint(
            "tenant_id",
            "promotion_id",
            "nm_id",
            "source",
            name="uq_wb_promo_nomenclature",
        ),
    )
    op.create_index(
        "ix_wb_promotion_nomenclature_tenant_id",
        "wb_promotion_nomenclature",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_wb_promo_nom_tenant_promo",
        "wb_promotion_nomenclature",
        ["tenant_id", "promotion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wb_promo_nom_tenant_promo", table_name="wb_promotion_nomenclature")
    op.drop_index(
        "ix_wb_promotion_nomenclature_tenant_id",
        table_name="wb_promotion_nomenclature",
    )
    op.drop_table("wb_promotion_nomenclature")
    op.drop_index("ix_wb_promotion_tenant_id", table_name="wb_promotion")
    op.drop_table("wb_promotion")
