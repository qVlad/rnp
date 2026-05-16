"""wb_payment_order.upd_delivery_amount + report_type — поля из бухгалтерского
xlsx «Стас Разметка банка».

Стас вручную проставляет в xlsx за каждый weekly-отчёт колонку «УПД Доставка
по выкупу» (Z) — небольшая сумма (1-2k₽) от отдельного УПД-документа WB
который зачитывается в налоговую базу АУСН-Доходы. Это не то же самое что
`wb_redeem_notification.total_sum_with_vat` (там полная стоимость возвратов).

Добавляем колонку чтобы хранить эту сумму при импорте xlsx, и поле
`report_type` ('Основной' / 'По выкупам') для корректного применения
методики Стаса (ВЗЗ только для Основной, разные правила месячного
бакетирования).

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-15 17:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "upd_delivery_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "report_type",
            sa.String(length=16),
            nullable=True,
        ),
    )
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "period_end",
            sa.Date(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("wb_payment_order", "period_end")
    op.drop_column("wb_payment_order", "report_type")
    op.drop_column("wb_payment_order", "upd_delivery_amount")
