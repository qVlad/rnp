"""plan_edit_requests — заявки manager'а на изменение плана (TASK-DEV-017).

Manager видит /plans read-only. Раньше — звонил директору. Теперь:
manager жмёт «Предложить правку» → создаёт запись → TG-notification
директорам тенанта. Director смотрит, accept (= apply + close) или
reject (= close с причиной).

Жёсткий MVP-scope:
  - Одно поле за раз (не вся строка плана)
  - Status: pending / accepted / rejected
  - resolved_by + resolved_at + резолюция (комментарий)
  - Простая table, без separate workflow-state-machine

Revision ID: 0053
Revises: 0052
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_edit_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey("sales_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("current_value", sa.Numeric(18, 4), nullable=True),
        sa.Column("requested_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_plan_edit_requests_status",
        "plan_edit_requests",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_plan_edit_requests_plan",
        "plan_edit_requests",
        ["plan_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_plan_edit_requests_plan", table_name="plan_edit_requests")
    op.drop_index("ix_plan_edit_requests_status", table_name="plan_edit_requests")
    op.drop_table("plan_edit_requests")
