"""UNIT-PLAN Sprint 1 Lane A: справочники тарифов WB (box / pallet / commission).

Reference-таблицы БЕЗ `tenant_id` — тарифы WB одинаковы для всех селлеров,
тенант-специфика выносится в `unit_plan_override` (миграция 0042).

SCD Type 2: при ежедневном sync с WB Tariffs API
(`/api/v1/tariffs/{box,pallet,commission}`) — если данные изменились, добавляем
новую запись с `effective_from = today`; если не изменились — обновляем только
`fetched_at`. Расчёт на дату D берёт «последнюю запись на/до D».

См. `UNIT_PLAN.md` §3, `WB_API_REFERENCE.md` (Tariffs API, scope bit 512).

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- wb_tariff_box -------------------------------------------------------
    op.create_table(
        "wb_tariff_box",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("warehouse_name", sa.String(255), nullable=False),
        sa.Column(
            "delivery_base",
            sa.Numeric(10, 4),
            nullable=True,
            comment="₽ за 1 л (базовая стоимость доставки)",
        ),
        sa.Column(
            "delivery_liter",
            sa.Numeric(10, 4),
            nullable=True,
            comment="₽ за каждый дополнительный литр",
        ),
        sa.Column(
            "delivery_expr",
            sa.Numeric(8, 4),
            nullable=True,
            comment="% коэффициент склада",
        ),
        sa.Column(
            "storage_base",
            sa.Numeric(10, 6),
            nullable=True,
            comment="₽/день за 1 л (базовая стоимость хранения)",
        ),
        sa.Column("storage_liter", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "dt_next",
            sa.Date(),
            nullable=True,
            comment="WB-hint когда изменится тариф",
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "warehouse_name", "effective_from", name="uq_wb_tariff_box_wh_eff"
        ),
    )
    op.create_index(
        "idx_wb_tariff_box_eff",
        "wb_tariff_box",
        [sa.text("effective_from DESC")],
    )

    # --- wb_tariff_pallet ----------------------------------------------------
    op.create_table(
        "wb_tariff_pallet",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("warehouse_name", sa.String(255), nullable=False),
        sa.Column("delivery_base", sa.Numeric(10, 4), nullable=True),
        sa.Column("delivery_liter", sa.Numeric(10, 4), nullable=True),
        sa.Column("delivery_expr", sa.Numeric(8, 4), nullable=True),
        sa.Column("storage_base", sa.Numeric(10, 6), nullable=True),
        sa.Column("storage_liter", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "storage_expr",
            sa.Numeric(8, 4),
            nullable=True,
            comment="% коэффициент хранения (только у pallet)",
        ),
        sa.Column("dt_next", sa.Date(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "warehouse_name", "effective_from", name="uq_wb_tariff_pallet_wh_eff"
        ),
    )
    op.create_index(
        "idx_wb_tariff_pallet_eff",
        "wb_tariff_pallet",
        [sa.text("effective_from DESC")],
    )

    # --- wb_tariff_commission -----------------------------------------------
    op.create_table(
        "wb_tariff_commission",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("subject_name", sa.String(255), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column(
            "commission_fbo",
            sa.Numeric(6, 2),
            nullable=True,
            comment="kgvpMarketplace — комиссия FBO %",
        ),
        sa.Column(
            "commission_fbs",
            sa.Numeric(6, 2),
            nullable=True,
            comment="kgvpSupplier — комиссия FBS %",
        ),
        sa.Column("commission_express", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "paid_storage_kgvp",
            sa.Numeric(6, 2),
            nullable=True,
            comment="% платной приёмки (если в этом ответе)",
        ),
        sa.Column("return_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "subject_name", "effective_from", name="uq_wb_tariff_commission_subj_eff"
        ),
    )
    op.create_index(
        "idx_wb_tariff_commission_subj_eff",
        "wb_tariff_commission",
        ["subject_name", sa.text("effective_from DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_wb_tariff_commission_subj_eff", table_name="wb_tariff_commission"
    )
    op.drop_table("wb_tariff_commission")
    op.drop_index("idx_wb_tariff_pallet_eff", table_name="wb_tariff_pallet")
    op.drop_table("wb_tariff_pallet")
    op.drop_index("idx_wb_tariff_box_eff", table_name="wb_tariff_box")
    op.drop_table("wb_tariff_box")
