"""Чарджбэки / штрафы / списания WB — таблицы chargebacks + chargeback_history.

Реализация LEAD-005 (см. agents/references/spec-chargebacks.md). Хранит:
- chargebacks: лента «проблемных» списаний WB (Штрафы, Удержания, Коррекции,
  Платная приёмка, Хранение с низким ИЛ, …) с workflow оспаривания
- chargeback_history: журнал переходов статусов (audit trail)

Парсер `sync_chargebacks()` сканирует `wb_report_detail` по словарю
оспоримых `supplier_oper_name` и создаёт записи в статусе `new`.
UNIQUE(tenant_id, rrd_id, category) обеспечивает идемпотентность.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-18 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chargebacks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Идентификация в wb_report_detail (для дедупликации)
        sa.Column("rrd_id", sa.BigInteger(), nullable=False),
        sa.Column("realizationreport_id", sa.BigInteger(), nullable=True),
        # Классификация
        sa.Column(
            "category",
            sa.String(32),
            nullable=False,
            comment="penalty/deduction/delivery_correction/sale_correction/"
            "acquiring_correction/loyalty_correction/low_il_storage_fee/"
            "paid_acceptance/damage_compensation/voluntary_compensation",
        ),
        sa.Column("supplier_oper_name", sa.String(128), nullable=False),
        # Финансы
        sa.Column(
            "amount_rub",
            sa.Numeric(14, 2),
            nullable=False,
            comment="Абсолютная сумма списания. Знак подразумевается по category "
            "(damage_compensation = в плюс, остальные = в минус)",
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        # Workflow
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'new'"),
            comment="new/disputing/resolved_recovered/resolved_rejected/cancelled/auto_closed",
        ),
        # Даты
        sa.Column("operation_dt", sa.Date(), nullable=True),
        sa.Column("rr_dt", sa.Date(), nullable=True),
        # Свободные поля
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=True),
        sa.Column("claim_filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wb_response", sa.Text(), nullable=True),
        sa.Column("wb_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovered_amount", sa.Numeric(14, 2), nullable=True),
        # Audit
        sa.Column(
            "created_by",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "rrd_id", "category", name="uq_chargeback_dedup"
        ),
    )
    op.create_index(
        "idx_chargebacks_period",
        "chargebacks",
        ["tenant_id", "operation_dt"],
    )
    op.create_index(
        "idx_chargebacks_status",
        "chargebacks",
        ["tenant_id", "status"],
    )

    op.create_table(
        "chargeback_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "chargeback_id",
            sa.BigInteger(),
            sa.ForeignKey("chargebacks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("chargeback_history")
    op.drop_index("idx_chargebacks_status", table_name="chargebacks")
    op.drop_index("idx_chargebacks_period", table_name="chargebacks")
    op.drop_table("chargebacks")
