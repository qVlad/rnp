"""wb_redeem_notification — кэш уведомлений о выкупе из WB Documents API.

WB ежедневно выкупает товары селлера (потерянные/повреждённые/правила) и
шлёт «Уведомление о выкупе» отдельным документом. Эти суммы — доход в УСН,
но НЕ приходят через `/api/finance/v1/sales-reports/detailed`. Источник —
WB Documents API (`https://documents-api.wildberries.ru`), категория
`redeem-notification`. Документ — ZIP с XLSX внутри.

Структура одного XLSX:
  A3: «УВЕДОМЛЕНИЕ О ВЫКУПЕ №<num> от <date>»
  Строка 10: заголовки (№, Артикул, Наименование, Кол-во, Сумма выкупа, ...)
  Строки 11+: товарные позиции
  Строка «Итого»: финальная сумма (col E = Сумма выкупа вкл. НДС)

Items сохраняем в JSONB для прозрачности — отдельные строки в БД не нужны
(в среднем 1-4 позиции на документ, частота 1-2 в неделю).

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-14 17:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_redeem_notification",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_number", sa.String(64), nullable=False),
        sa.Column("notification_date", sa.Date(), nullable=False),
        sa.Column("total_sum_with_vat", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("items", JSONB(), nullable=True),
        sa.Column("service_name", sa.String(128), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "notification_number"),
    )
    op.create_index(
        "ix_redeem_tenant_date",
        "wb_redeem_notification",
        ["tenant_id", "notification_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_redeem_tenant_date", table_name="wb_redeem_notification")
    op.drop_table("wb_redeem_notification")
