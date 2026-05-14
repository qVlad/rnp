"""wb_offset_act — кэш Актов взаимозачёта (WB Documents API: actprofit).

Параллельно `wb_redeem_notification`: WB отдельным документом оформляет
взаимозачёт по выписанным УПД (например, услуга доставки удерживается из
суммы выкупа). Эти суммы — отдельный приход/расход для УСН-учёта.

Структура XLSX (предположительно аналогична redeem-notification):
  - шапка с номером и датой документа
  - строки позиций
  - итог в строке «Итого»

На проде клиент не имеет актов за последние 5 мес — реальный формат
будет известен когда WB сгенерирует первый. Парсер написан consistent
с redeem-notification, конкретные расхождения подкрутим при появлении
данных.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-14 19:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_offset_act",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("act_number", sa.String(64), nullable=False),
        sa.Column("act_date", sa.Date(), nullable=False),
        sa.Column("total_sum", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("items", JSONB(), nullable=True),
        sa.Column("service_name", sa.String(128), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "act_number"),
    )
    op.create_index("ix_offset_act_tenant_date", "wb_offset_act", ["tenant_id", "act_date"])


def downgrade() -> None:
    op.drop_index("ix_offset_act_tenant_date", table_name="wb_offset_act")
    op.drop_table("wb_offset_act")
