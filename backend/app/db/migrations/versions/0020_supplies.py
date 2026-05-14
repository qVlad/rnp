"""supplies — закупки товара у поставщиков (для COGS weighted-average).

Для расчёта себестоимости методом скользящей средней (как в 1С) нам нужно
знать историю закупок: даты, количества, цены за единицу, статус оплаты
поставщику. Формула:

  средняя_стоимость = Σ(qty × cost_per_unit для paid supplies) / Σ(qty)

Только paid-supplies учитываются — это требование УСН-расходы (нельзя
списать в расход то что не оплачено).

Поля:
  nm_id           — WB SKU (FK products.nm_id)
  vendor_code     — артикул поставщика (для случая когда nm_id ещё не присвоен)
  supply_date     — дата поступления товара (для хронологии)
  qty             — количество единиц
  cost_per_unit   — закупочная цена за штуку (RUB)
  total_cost      — qty × cost_per_unit (хранится для удобства запросов)
  currency        — валюта закупки (RUB | CNY | USD), используется в отчётах
  vendor          — название поставщика
  invoice_number  — номер инвойса/счёта (опционально)
  paid_status     — unpaid | partial | paid
  paid_date       — когда оплатили (если paid/partial)
  paid_amount     — сумма фактической оплаты (для partial)
  notes           — свободные заметки

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-14 19:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("vendor_code", sa.String(255), nullable=True),
        sa.Column("supply_date", sa.Date(), nullable=False, index=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_per_unit", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("invoice_number", sa.String(128), nullable=True),
        sa.Column("paid_status", sa.String(16), nullable=False, server_default="unpaid"),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_supplies_nm_date", "supplies", ["nm_id", "supply_date"])
    op.create_index("ix_supplies_tenant_paid", "supplies", ["tenant_id", "paid_status"])


def downgrade() -> None:
    op.drop_index("ix_supplies_tenant_paid", table_name="supplies")
    op.drop_index("ix_supplies_nm_date", table_name="supplies")
    op.drop_table("supplies")
