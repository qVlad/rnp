"""add chrt_id and tech_size to wb_orders / wb_sales / wb_stocks_snapshot

WB API endpoints (orders, sales, stocks) возвращают `techSize` (строка типа "36",
"42-44", "L") для каждой строки. Поле нужно для распределения поставок по
размерам внутри кластера. `chrt_id` (Wildberries internal size id) пока ни один
из используемых endpoint'ов не отдаёт в текущем JSON, но добавлен заранее под
переход на `/api/analytics/v1/stocks-report/wb-warehouses` (там chrt_id есть).
Все поля nullable — старые строки заполнятся NULL и в подсчётах попадут в
«размер: —».

Индексы: композитный (nm_id, tech_size) для быстрых per-size агрегаций; для
stocks — расширяем существующий ix до (snapshot_dt, nm_id, warehouse_name,
tech_size) чтобы покрыть запросы supply_distribution.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-08 13:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("wb_orders", "wb_sales", "wb_stocks_snapshot"):
        op.add_column(table, sa.Column("chrt_id", sa.BigInteger(), nullable=True))
        op.add_column(table, sa.Column("tech_size", sa.String(64), nullable=True))
        op.create_index(
            f"ix_{table}_nm_size",
            table,
            ["nm_id", "tech_size"],
        )

    # Дополнительный индекс stocks для per-cluster + per-size агрегаций.
    op.create_index(
        "ix_stocks_dt_nm_wh_size",
        "wb_stocks_snapshot",
        ["snapshot_dt", "nm_id", "warehouse_name", "tech_size"],
    )


def downgrade() -> None:
    op.drop_index("ix_stocks_dt_nm_wh_size", table_name="wb_stocks_snapshot")
    for table in ("wb_orders", "wb_sales", "wb_stocks_snapshot"):
        op.drop_index(f"ix_{table}_nm_size", table_name=table)
        op.drop_column(table, "tech_size")
        op.drop_column(table, "chrt_id")
