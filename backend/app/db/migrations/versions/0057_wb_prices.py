"""wb_prices + wb_prices_size — актуальные цены продавца из WB Prices API.

Источник правды для базовой цены и скидки в `/unit-plan`. До этой миграции
`services/unit_plan_loader._latest_price` тянул цену из последней проданной
строки `wb_sales` — это даёт устаревшие/расходящиеся цифры для SKU, которые
давно не продавались, или после ручного изменения цены в ЛК WB.

Sync через `sync/tasks_prices.sync_wb_prices` раз в 30 мин (Celery beat),
endpoint WB: `GET https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter`.

Хранение — «последнее значение, перезаписывая» (ON CONFLICT DO UPDATE).
Историю не дублируем — она доступна через `wb_sales` (фактические цены
продажи) и `unit_plan_snapshot` (snapshot'ы UNIT-плана).

`wb_prices_size` — опциональная per-size таблица для случая
`editableSizePrice=true` (размерная A/B). `/unit-plan` агрегирует по `nm_id`,
размерная разбивка — отдельная задача в backlog.

Revision ID: 0057
Revises: 0056
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_prices",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "price",
            sa.Numeric(12, 2),
            nullable=True,
            comment="Базовая цена продавца (до скидки), ₽",
        ),
        sa.Column(
            "discount_pct",
            sa.Numeric(5, 2),
            nullable=True,
            comment="Скидка продавца, 0-100",
        ),
        sa.Column(
            "club_discount_pct",
            sa.Numeric(5, 2),
            nullable=True,
            comment="Скидка WB Клуб (per-nm override, если есть)",
        ),
        sa.Column(
            "editable_size_price",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Если true — см. wb_prices_size для per-size прайсов",
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
        sa.PrimaryKeyConstraint("tenant_id", "nm_id", name="pk_wb_prices"),
    )
    op.create_index(
        "ix_wb_prices_synced",
        "wb_prices",
        ["tenant_id", sa.text("synced_at DESC")],
    )

    op.create_table(
        "wb_prices_size",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("tech_size", sa.String(64), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "nm_id", "tech_size", name="pk_wb_prices_size"
        ),
    )


def downgrade() -> None:
    op.drop_table("wb_prices_size")
    op.drop_index("ix_wb_prices_synced", table_name="wb_prices")
    op.drop_table("wb_prices")
