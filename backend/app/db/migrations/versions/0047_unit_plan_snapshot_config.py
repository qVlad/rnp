"""UNIT_PLAN.md §10: freeze global_config в момент snapshot'а.

Без этой таблицы `/snapshots/{id}/diff` сравнивал текущий compute_row (с
текущим global_config) против сохранённых rows. Если между snapshot'ом и
сегодня директор подкрутил `tax_pct` или `marketing_pct` — diff показывал
«данные изменились», хотя на самом деле изменились только константы.

Эта таблица хранит замороженную копию `unit_plan_global_config` в момент
создания snapshot'а. PK по `(tenant_id, snapshot_date, label)` совпадает с
identity снапшота. Снапшот без config-row → diff fallback'ит на current cfg
(legacy snapshots, созданные до миграции).

Revision ID: 0047
Revises: 0046
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unit_plan_snapshot_config",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        # Денормализованная копия unit_plan_global_config (миграции 0042, 0046)
        sa.Column("wb_club_pct", sa.Numeric(5, 2)),
        sa.Column("spp_default_pct", sa.Numeric(5, 2)),
        sa.Column("spp_by_subject", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("wb_wallet_pct", sa.Numeric(5, 2)),
        sa.Column("acquiring_pct", sa.Numeric(5, 2)),
        sa.Column("il_coef", sa.Numeric(6, 4)),
        sa.Column("irp_coef", sa.Numeric(6, 4)),
        sa.Column("marketing_pct", sa.Numeric(5, 2)),
        sa.Column("tax_pct", sa.Numeric(5, 2)),
        sa.Column("vat_mode", sa.String(16)),
        sa.Column("vat_pct", sa.Numeric(5, 2)),
        sa.Column("acceptance_rub_per_liter", sa.Numeric(6, 2)),
        sa.Column("acceptance_multiplier", sa.Numeric(6, 2)),
        sa.Column("velocity_days", sa.Integer()),
        sa.Column("buyout_fallback_pct", sa.Numeric(5, 2)),
        sa.Column("storage_days", sa.Integer()),
        sa.Column(
            "reverse_logistics_mode",
            sa.String(16),
            nullable=False,
            server_default="tariff",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            "label",
            name="uq_unit_plan_snapshot_cfg",
        ),
    )
    op.create_index(
        "ix_unit_plan_snapshot_cfg_tenant",
        "unit_plan_snapshot_config",
        ["tenant_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_unit_plan_snapshot_cfg_tenant",
        table_name="unit_plan_snapshot_config",
    )
    op.drop_table("unit_plan_snapshot_config")
