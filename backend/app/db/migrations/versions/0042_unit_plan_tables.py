"""UNIT-PLAN Sprint 1 Lane A: tenant-scoped план-таблицы.

3 таблицы:

- `unit_plan_global_config` — версионируемый набор глобальных констант
  (СПП default, налог, НДС, эквайринг, ИЛ/ИРП-коэф, приёмка ₽/л, …).
  Versioning через UNIQUE (tenant_id, effective_date); расчёт берёт
  «latest на/до today».
- `unit_plan_override` — per-row override поверх products / global_config
  (склад, FBS-флаг, монопаллет, СПП, ABC/season/gender labels, comment).
- `unit_plan_snapshot` — иммутабельная фотография расчёта на дату
  (denormalized для дешёвого diff между snapshots, см. UNIT_PLAN.md §10).

См. `UNIT_PLAN.md` §3 (DDL), §2 (Excel cell → поле БД mapping), §10 (snapshots).

Revision ID: 0042
Revises: 0041
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- unit_plan_global_config --------------------------------------------
    op.create_table(
        "unit_plan_global_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("effective_date", sa.Date(), nullable=False),
        # Pricing ladder
        sa.Column(
            "wb_club_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "spp_default_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "spp_by_subject",
            JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment="Per-категория override {'Пижамы': 28, ...}",
        ),
        sa.Column(
            "wb_wallet_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "acquiring_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("2"),
        ),
        # Coefs
        sa.Column(
            "il_coef",
            sa.Numeric(6, 4),
            nullable=True,
            server_default=sa.text("1.16"),
        ),
        sa.Column(
            "irp_coef",
            sa.Numeric(6, 4),
            nullable=True,
            server_default=sa.text("0.017"),
        ),
        # Cost percentages
        sa.Column(
            "marketing_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "tax_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("8"),
        ),
        sa.Column(
            "vat_mode",
            sa.String(16),
            nullable=True,
            server_default=sa.text("'exclude'"),
            comment="'include' | 'exclude' | 'none'",
        ),
        sa.Column(
            "vat_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("10"),
        ),
        # Acceptance
        sa.Column(
            "acceptance_rub_per_liter",
            sa.Numeric(6, 2),
            nullable=True,
            server_default=sa.text("1.7"),
        ),
        sa.Column(
            "acceptance_multiplier",
            sa.Numeric(6, 2),
            nullable=True,
            server_default=sa.text("1.0"),
        ),
        # Velocity / fallback
        sa.Column(
            "velocity_days",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "buyout_fallback_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("50"),
        ),
        sa.Column(
            "storage_days",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id", "effective_date", name="uq_unit_plan_global_config_eff"
        ),
    )

    # --- unit_plan_override -------------------------------------------------
    op.create_table(
        "unit_plan_override",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        # Per-row overrides поверх products / global_config
        sa.Column("warehouse_name", sa.String(255), nullable=True),
        sa.Column("is_fbs", sa.Boolean(), nullable=True),
        sa.Column("is_monopallet", sa.Boolean(), nullable=True),
        sa.Column("items_per_monopallet", sa.Integer(), nullable=True),
        sa.Column("spp_pct", sa.Numeric(5, 2), nullable=True),
        # Labels
        sa.Column("abc_label", sa.CHAR(1), nullable=True),
        sa.Column("season_label", sa.String(32), nullable=True),
        sa.Column("gender_label", sa.String(8), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "nm_id", name="uq_unit_plan_override_nm"),
    )

    # --- unit_plan_snapshot -------------------------------------------------
    op.create_table(
        "unit_plan_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        # Denormalized: ровно то что считалось в день снапшота
        sa.Column("orders_qty", sa.Integer(), nullable=True),
        sa.Column("sold_qty", sa.Integer(), nullable=True),
        sa.Column("revenue", sa.Numeric(14, 2), nullable=True),
        sa.Column("profit_rub", sa.Numeric(14, 2), nullable=True),
        sa.Column("margin_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("buyout_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_unit_plan_snapshot",
        "unit_plan_snapshot",
        ["tenant_id", "snapshot_date", "nm_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_unit_plan_snapshot", table_name="unit_plan_snapshot")
    op.drop_table("unit_plan_snapshot")
    op.drop_table("unit_plan_override")
    op.drop_table("unit_plan_global_config")
