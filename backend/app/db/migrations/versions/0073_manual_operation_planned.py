"""manual_operation.is_planned — обязательства в ДДС (planned operations).

TASK-DEV-054: планируемые операции (как TS obligationReceivable/Payable) — не
входят в баланс, показываются отдельной колонкой в ДДС-календаре.

Revision ID: 0073
Revises: 0072
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0073"
down_revision: Union[str, None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manual_operation",
        sa.Column("is_planned", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("manual_operation", "is_planned")
