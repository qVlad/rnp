"""wb_paid_storage — отчёт WB о платном хранении с разбивкой по SKU.

WB Analytics API `/api/v1/paid_storage` возвращает суточные строки:
один nm_id × один склад × одна дата. Идёт async-task'ом (см.
`integrations/wb/paid_storage.py`). Используется в unit_economics
для точного отнесения хранения на SKU вместо пропорционального
распределения общего `wb_report_detail.storage_fee`.

Уникальный ключ: (date, nm_id, warehouse, chrt_id) — может быть
несколько строк на ту же связку с разными chrt_id (размерами).

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-08 14:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_paid_storage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("chrt_id", sa.BigInteger(), nullable=True),
        sa.Column("tech_size", sa.String(64), nullable=True),
        sa.Column("barcode", sa.String(64), nullable=True),
        sa.Column("vendor_code", sa.String(255), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("warehouse", sa.String(255), nullable=True),
        sa.Column("office_id", sa.BigInteger(), nullable=True),
        sa.Column("calc_type", sa.String(128), nullable=True),
        # Цена хранения за сутки (₽). Используем Numeric (12,4) — у WB бывают
        # дробные коп. в хранении.
        sa.Column("warehouse_price", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("barcodes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("volume", sa.Numeric(12, 4), nullable=True),
        sa.Column("warehouse_coef", sa.Numeric(8, 4), nullable=True),
        sa.Column("log_warehouse_coef", sa.Numeric(8, 4), nullable=True),
        sa.Column("loyalty_discount", sa.Numeric(12, 4), nullable=True),
        sa.Column("pallet_place_code", sa.String(64), nullable=True),
        sa.Column("pallet_count", sa.Integer(), nullable=True),
        sa.Column("original_date", sa.Date(), nullable=True),
        sa.Column("tariff_fix_date", sa.Date(), nullable=True),
        sa.Column("tariff_lower_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_paid_storage_date_nm",
        "wb_paid_storage",
        ["date", "nm_id"],
    )
    op.create_index(
        "ix_paid_storage_nm_size",
        "wb_paid_storage",
        ["nm_id", "tech_size"],
    )
    op.create_unique_constraint(
        "uq_paid_storage_key",
        "wb_paid_storage",
        ["date", "nm_id", "chrt_id", "warehouse"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_paid_storage_key", "wb_paid_storage", type_="unique")
    op.drop_index("ix_paid_storage_nm_size", table_name="wb_paid_storage")
    op.drop_index("ix_paid_storage_date_nm", table_name="wb_paid_storage")
    op.drop_table("wb_paid_storage")
