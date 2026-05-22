"""weekly_report_comment — серверный комментарий менеджера в `/weekly-report`.

До этой миграции комментарий хранился в `localStorage` — был «только мне»
(другой user открывает ту же неделю — у него пусто). Это блокировало
manager↔РОП коммуникацию: менеджер пишет «была акция, провал ожидаем», РОП
не видит, если PDF не отправили.

TASK-LEAD-062. Источник запроса — РОП feedback раунда 12.

Структура:
    weekly_report_comment(
      id              BIGSERIAL PRIMARY KEY,
      tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      brand           VARCHAR(255) NULL,         -- NULL = «по всем брендам» (РОП/director scope)
      week_start      DATE NOT NULL,             -- понедельник недели (UTC)
      comment         TEXT NOT NULL DEFAULT '',
      author_user_id  INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
      updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (tenant_id, brand, week_start)
    )

`brand` NULL = один общий комментарий за неделю на весь tenant (для РОПа /
собственника). Заполненный brand — комментарий менеджера к одному бренду.
В UI manager редактирует свои brand-комментарии (для каждого своего бренда —
свой), РОП видит всё + может оставить свой «over-scope» (brand=NULL).

Revision ID: 0058
Revises: 0057
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_report_comment",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "comment",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "author_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # UNIQUE с поддержкой NULL для brand: коалесцируем в спец-строку,
    # чтобы Postgres рассматривал NULL как «значение» в индексе.
    op.create_index(
        "uq_weekly_report_comment_tenant_brand_week",
        "weekly_report_comment",
        ["tenant_id", sa.text("COALESCE(brand, '__overall__')"), "week_start"],
        unique=True,
    )
    op.create_index(
        "ix_weekly_report_comment_tenant_week",
        "weekly_report_comment",
        ["tenant_id", "week_start"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_report_comment_tenant_week",
        table_name="weekly_report_comment",
    )
    op.drop_index(
        "uq_weekly_report_comment_tenant_brand_week",
        table_name="weekly_report_comment",
    )
    op.drop_table("weekly_report_comment")
