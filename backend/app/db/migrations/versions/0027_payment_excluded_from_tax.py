"""wb_payment_order.excluded_from_tax + exclusion_reason — флаг ручного
исключения отчёта из налоговой базы.

Используется для bookkeeper-overrides. Типичные случаи:

  1. Отчёт прошлого фискального года, оплата пришла в новом году. Уже
     учтён в декларации прошлого года — не должен попасть в новую базу.
  2. Возврат на ошибочный отчёт, выкуп не состоялся — корректировка.
  3. Внутренний взаимозачёт между периодами — двойной учёт.

И АУСН (`tax_report_ausn.py`), и УСН (`tax_report_usn.py`) учитывают флаг
одинаково — исключают строку из всех расчётных компонентов.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-15 20:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "excluded_from_tax",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "exclusion_reason",
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("wb_payment_order", "exclusion_reason")
    op.drop_column("wb_payment_order", "excluded_from_tax")
