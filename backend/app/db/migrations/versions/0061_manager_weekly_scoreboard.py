"""manager_weekly_scoreboard — pre-aggregated scoreboard для `/weekly-report/by-manager`.

TASK-LEAD-087. До этой миграции `/api/weekly-report/by-manager` делал
N×`compute_dashboard` (по числу менеджеров × 2 для WoW) — на тенантах с
10+ менеджерами заметно медленно (несколько секунд latency).

Решение: ночью Celery beat `sync.manager_scoreboard` (04:30 МСК, после
report_detail sync 04:15) пробегает per-tenant × per-manager × последних
4 недель → upsert в эту таблицу. Endpoint читает напрямую, fallback на
live-compute если week_start ещё не пред-агрегирован (новый менеджер,
pre-deploy период).

Структура:
    manager_weekly_scoreboard(
      tenant_id         BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      manager_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      week_start        DATE NOT NULL,
      revenue           NUMERIC(18,2) NOT NULL DEFAULT 0,
      margin            NUMERIC(18,2) NOT NULL DEFAULT 0,
      margin_pct        NUMERIC(8,2)  NOT NULL DEFAULT 0,
      orders            INTEGER NOT NULL DEFAULT 0,
      returns           INTEGER NOT NULL DEFAULT 0,
      prev_revenue      NUMERIC(18,2) NOT NULL DEFAULT 0,
      prev_margin_pct   NUMERIC(8,2)  NOT NULL DEFAULT 0,
      wow_revenue_pct   NUMERIC(8,2)  NULL,
      wow_margin_pp     NUMERIC(8,2)  NOT NULL DEFAULT 0,
      brands            JSONB NOT NULL DEFAULT '[]',  -- snapshot бренд-назначений на момент агрегата
      no_brands         BOOLEAN NOT NULL DEFAULT FALSE,
      manager_name      VARCHAR(255) NULL,  -- denorm full_name|username для отчётов
      updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (tenant_id, manager_user_id, week_start)
    )

Revision ID: 0061
Revises: 0060
Create Date: 2026-05-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manager_weekly_scoreboard",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "manager_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "revenue",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "margin",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "margin_pct",
            sa.Numeric(8, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "orders",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "returns",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "prev_revenue",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "prev_margin_pct",
            sa.Numeric(8, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("wow_revenue_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "wow_margin_pp",
            sa.Numeric(8, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "brands",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "no_brands",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("manager_name", sa.String(255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "manager_user_id",
            "week_start",
            name="pk_manager_weekly_scoreboard",
        ),
    )
    # Главный access pattern: tenant + week_start → list of managers.
    op.create_index(
        "ix_manager_weekly_scoreboard_tenant_week",
        "manager_weekly_scoreboard",
        ["tenant_id", "week_start"],
    )
    # tenant_id отдельным индексом — для FK-сканов / потенциальных join'ов.
    op.create_index(
        "ix_manager_weekly_scoreboard_tenant",
        "manager_weekly_scoreboard",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manager_weekly_scoreboard_tenant",
        table_name="manager_weekly_scoreboard",
    )
    op.drop_index(
        "ix_manager_weekly_scoreboard_tenant_week",
        table_name="manager_weekly_scoreboard",
    )
    op.drop_table("manager_weekly_scoreboard")
