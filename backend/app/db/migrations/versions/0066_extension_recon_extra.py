"""extension_recon_extra — реклама/заказы из ЛК WB через extension (TASK-LEAD-141).

Правила 9 (Реклама ВБ.Продвижение), 10 (Кол-во заказов), 11 (Сумма заказов)
не входят в отчёт реализации — они в других разделах ЛК WB (Продвижение →
Финансы и Воронка продаж). Extension перехватывает эти страницы и шлёт сюда.

Одна строка на неделю (tenant, week_start). Колонки nullable — реклама и
заказы приходят с разных страниц, UPSERT обновляет только пришедшие поля
(COALESCE — не затираем то что уже есть).

Revision ID: 0066
Revises: 0065
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extension_recon_extra",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("ad_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("orders_count", sa.Integer(), nullable=True),
        sa.Column("orders_sum", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "week_start", name="uq_extension_recon_extra_tenant_week"
        ),
    )


def downgrade() -> None:
    op.drop_table("extension_recon_extra")
