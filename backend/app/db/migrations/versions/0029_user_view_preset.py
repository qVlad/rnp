"""user_view_preset — сохранённые «пресеты» страниц (Dashboard / Units / P&L).

Один user может сохранять несколько именованных конфигураций для каждой
страницы: например «ежедневный обзор» (период=day, режим=preliminary,
скрыты revenue/orders/buyout), «недельный отчёт» (период=week, режим=final,
все KPI). При следующем заходе — выбирает из dropdown.

Структура:
- `scope` — какая страница: 'dashboard' | 'units' | 'pnl'
- `name` — название пресета (32 chars max)
- `state` — JSONB произвольный (фронт сериализует свой state туда)
- `is_default` — за-загрузить автоматически при открытии страницы

Уникальность: (tenant_id, user_id, scope, name) — у одного юзера в рамках
одного scope имена не дублируются.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-15 21:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_view_preset",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("scope", sa.String(length=32), nullable=False, index=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
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
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_user_view_preset_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            ondelete="CASCADE",
            name="fk_user_view_preset_user",
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "scope", "name",
            name="uq_user_view_preset_name",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_view_preset")
