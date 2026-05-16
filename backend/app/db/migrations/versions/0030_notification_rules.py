"""notification_rule — настраиваемые алерты (правила-триггеры).

User может определить правила вида «если остаток SKU < 50 шт → отправить
в Telegram». Engine (`services/notification_engine.py`) бежит по Celery
beat (раз в час), проверяет все active rules, отправляет уведомления.

Поля:
- `metric` — какой показатель проверяем (stock_below, dts_below,
  daily_revenue_below, drr_above, kassa_below_forecast, returns_pct_above)
- `operator` — '<', '>', '<=', '>=' (subset; пока только < и >)
- `threshold` — значение для сравнения
- `scope_filter` — JSON: { nm_ids?: [], brands?: [], ...} опционально
- `channel` — пока только 'telegram'
- `cooldown_minutes` — не флужим: после firing молчим N минут (default 1440)
- `last_fired_at` — для cooldown
- `is_active` — флаг включения

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-15 22:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), nullable=True, index=True),  # null = system rule
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("operator", sa.String(length=4), nullable=False),  # '<' '>' '<=' '>='
        sa.Column("threshold", sa.Numeric(14, 4), nullable=False),
        sa.Column("scope_filter", JSONB(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="telegram"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "cooldown_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",  # 24h по умолчанию
        ),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fire_payload", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_notification_rule_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL",
            name="fk_notification_rule_user",
        ),
    )
    op.create_index(
        "ix_notification_rule_active",
        "notification_rule",
        ["tenant_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_rule_active", table_name="notification_rule")
    op.drop_table("notification_rule")
