"""wb_payment_order: per-regime exclusion flags.

Сценарий: бухгалтер может вручную исключить отчёт из одной налоговой
методики, но оставить в другой. Реальный кейс — отчёт 572437010
(12-15..12-21 paid 01-12): бухгалтер ИСКЛЮЧАЕТ его из УСН Jan (потому что
относится к 2025 фискальному году), но ВКЛЮЧАЕТ в АУСН Jan (cash-basis,
деньги пришли в Jan).

Поля:
- `excluded_from_ausn` — не учитывать в `tax_report_ausn.build_ausn_monthly_report`
- `excluded_from_usn` — не учитывать в `tax_report_usn.build_usn_monthly_report`

Поле `excluded_from_tax` (из 0027) оставляем для backward compat —
интерпретируется как «не учитывать в обоих режимах», если новые флаги
не выставлены.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-15 20:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "excluded_from_ausn",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "wb_payment_order",
        sa.Column(
            "excluded_from_usn",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # Backfill: если в 0027 уже стоит excluded_from_tax=true, переносим
    # на оба новых флага (исключение из обоих режимов).
    op.execute(
        "UPDATE wb_payment_order SET excluded_from_ausn=true, excluded_from_usn=true "
        "WHERE excluded_from_tax=true"
    )


def downgrade() -> None:
    op.drop_column("wb_payment_order", "excluded_from_usn")
    op.drop_column("wb_payment_order", "excluded_from_ausn")
