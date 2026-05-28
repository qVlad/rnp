"""wb_funnel_daily — per-day заказы/выкупы/выручка из WB Analytics API.

Источник: POST /api/analytics/v3/sales-funnel/products/history (та же API,
на которой стоит Воронка ЛК). В отличие от Statistics API /supplier/orders,
ВКЛЮЧАЕТ заказы в рассрочку («Оплата частями») — поэтому цифры идентичны
дашборду WB.

Заменяет wb_orders/wb_sales как авторитетный источник для:
- /unit-plan «Заказано/Выкуплено П1/П2/П3» (TASK-LEAD-153)
- /dashboard preliminary KPI (orders_count, revenue_gross, buyouts_count)

wb_orders/wb_sales остаются для drill-down по бренду/региону/cancel-rate —
там нужна гранулярность, а ~20% недосчёт рассрочки не критичен.

PK (tenant_id, nm_id, dt) — один день на nm. Sync rolling 90 дней
ежедневно 06:00 MSK (после orders/sales sync).

Revision ID: 0067
Revises: 0066
Create Date: 2026-05-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_funnel_daily",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("dt", sa.Date(), nullable=False),
        sa.Column("orders_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buyouts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "orders_sum_rub", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("open_count", sa.Integer(), nullable=True),
        sa.Column("cart_count", sa.Integer(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "nm_id", "dt", name="pk_wb_funnel_daily"),
    )
    op.create_index(
        "idx_wb_funnel_daily_tenant_dt",
        "wb_funnel_daily",
        ["tenant_id", "dt"],
    )


def downgrade() -> None:
    op.drop_index("idx_wb_funnel_daily_tenant_dt", table_name="wb_funnel_daily")
    op.drop_table("wb_funnel_daily")
