"""wb_payment_order — История платежей из ЛК WB (XLSX-импорт).

Публичного API WB для страницы «История платежей» нет (private BFF, не
документирован). Бухгалтер выгружает XLSX-файл из ЛК → юзер загружает
его в наш сервис → строки попадают сюда.

Используется в `services/tax_report_ausn.py` для расчёта АУСН-Доходы:
если в системе есть payment_orders за нужный месяц — Bank-агрегат
строится по фактическим `paid_dt`, а не по proxy `report_date_to + N`.

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-15 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_payment_order",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        # Формат "4400004/53" — id селлера / порядковый номер заявки
        sa.Column("payment_order_id", sa.String(length=64), nullable=False),
        sa.Column("created_dt", sa.Date(), nullable=False, index=True),
        # null если статус ещё "Оплата обрабатывается". index создаётся
        # явным compound (tenant_id, paid_dt) ниже.
        sa.Column("paid_dt", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="RUB",
        ),
        # 'processing' | 'paid' | 'failed' (см. payment_orders.py:_normalize_status)
        sa.Column("status", sa.String(length=32), nullable=False),
        # Сырой текст из колонки «Статус оплаты» (для дебага)
        sa.Column("status_raw", sa.String(length=255), nullable=True),
        sa.Column("bank_comment", sa.String(length=512), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "payment_order_id", name="pk_wb_payment_order"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_wb_payment_order_tenant",
        ),
    )
    op.create_index(
        "ix_wb_payment_order_paid_dt",
        "wb_payment_order",
        ["tenant_id", "paid_dt"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wb_payment_order_paid_dt", table_name="wb_payment_order"
    )
    op.drop_table("wb_payment_order")
