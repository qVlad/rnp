"""wb_transit_tariff — тарифы транзитных направлений из ЛК WB.

TASK-LEAD-078 (2026-05-22). Тарифы транзита WB Tariffs API публично НЕ
отдаёт — они доступны только в личном кабинете seller.wildberries.ru на
странице «Поставки и заказы → Поставки (FBW) → Транзитные направления».

Расширение РНП перехватывает internal-fetch'и WB-фронта (через MAIN-world
interceptor) и шлёт распарсенные пары на backend. См.
`extension/src/content/wb-transit-tariffs-*.ts` и
`POST /api/transit-tariffs/upload`.

Структура:
    wb_transit_tariff(
      id                     BIGSERIAL PRIMARY KEY,
      tenant_id              BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      hub_name               VARCHAR(255) NOT NULL,   -- транзитный склад
      destination_warehouse  VARCHAR(255) NOT NULL,   -- конечный склад
      rate_small             NUMERIC(10, 4),          -- ₽/л при объёме < threshold
      rate_large             NUMERIC(10, 4),          -- ₽/л при объёме >= threshold
      threshold_l            NUMERIC(10, 2) DEFAULT 1500,
      currency               VARCHAR(8) DEFAULT 'RUB',
      synced_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (tenant_id, hub_name, destination_warehouse)
    )

Revision ID: 0059
Revises: 0058
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_transit_tariff",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hub_name", sa.String(255), nullable=False),
        sa.Column("destination_warehouse", sa.String(255), nullable=False),
        sa.Column("rate_small", sa.Numeric(10, 4), nullable=True),
        sa.Column("rate_large", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "threshold_l",
            sa.Numeric(10, 2),
            nullable=True,
            server_default=sa.text("1500"),
        ),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_wb_transit_tariff_tenant_hub_dest",
        "wb_transit_tariff",
        ["tenant_id", "hub_name", "destination_warehouse"],
        unique=True,
    )
    op.create_index(
        "ix_wb_transit_tariff_tenant_hub",
        "wb_transit_tariff",
        ["tenant_id", "hub_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wb_transit_tariff_tenant_hub",
        table_name="wb_transit_tariff",
    )
    op.drop_index(
        "uq_wb_transit_tariff_tenant_hub_dest",
        table_name="wb_transit_tariff",
    )
    op.drop_table("wb_transit_tariff")
