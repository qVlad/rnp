"""Перераспределение остатков WB — 5 таблиц + event-bus интеграция.

Реализация LEAD-008 (см. REDISTRIBUTION_PLAN.md). 5 таблиц:

- wb_lk_sessions — сохранённая сессия LK после SMS-логина (два JWT)
- redistribution_recommendations — ежедневные рекомендации «что куда везти»
- redistribution_tasks — очередь задач для окон 09:00/18:00 МСК
- redistribution_cooldowns — 72-часовой кулдаун на пару (chrt_id × склад)
- redistribution_roi_snapshots — дневные снапшоты ROI для еженедельного дайджеста

Все tenant-scoped (REDISTRIBUTION_PLAN §1.3) — модуль multi-tenant aware.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. WbLkSession ──────────────────────────────────────────────
    op.create_table(
        "wb_lk_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Кто из юзеров tenant'а сделал SMS-логин",
        ),
        sa.Column(
            "phone_last4",
            sa.String(4),
            nullable=True,
            comment="Последние 4 цифры телефона для отображения в UI",
        ),
        # Два JWT — оба зашифрованы AES-256-GCM (secrets_crypto)
        sa.Column(
            "authorize_v3_encrypted",
            sa.Text(),
            nullable=True,
            comment="RS256 JWT, долгоживущий (часы/дни), header AuthorizeV3 — encrypt() из secrets_crypto",
        ),
        sa.Column("authorize_v3_exp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "wb_seller_lk_encrypted",
            sa.Text(),
            nullable=True,
            comment="EdDSA JWT, TTL 5 минут, header Wb-Seller-Lk, refresh auto",
        ),
        sa.Column("wb_seller_lk_exp", sa.DateTime(timezone=True), nullable=True),
        # Контекст сессии (из JWT payload, для отладки и быстрой проверки)
        sa.Column("supplier_fid", sa.String(64), nullable=True),
        sa.Column("supplier_oid", sa.String(64), nullable=True),
        sa.Column("z_sid", sa.String(64), nullable=True, comment="Session UUID"),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("root_version", sa.String(32), nullable=True, comment="Версия фронта WB (v1.93.1)"),
        # Статус
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "needs_relogin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", name="uq_wb_lk_session_per_tenant"),
    )

    # ── 2. RedistributionRecommendation ────────────────────────────
    op.create_table(
        "redistribution_recommendations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "chrt_id",
            sa.BigInteger(),
            nullable=False,
            comment="Заявка в LK идёт по chrt_id, не nm_id — критично",
        ),
        sa.Column("from_office_id", sa.BigInteger(), nullable=True),
        sa.Column("from_office_name", sa.String(128), nullable=False),
        sa.Column("to_office_id", sa.BigInteger(), nullable=True),
        sa.Column("to_office_name", sa.String(128), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        # Экономика (в рублях, оценочно)
        sa.Column("expected_logistics_saving_rub", sa.Numeric(14, 2), nullable=True),
        sa.Column("expected_il_uplift_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("expected_revenue_uplift_rub", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "cost_share_rub",
            sa.Numeric(14, 2),
            nullable=True,
            comment="Доля +0.5% комиссии от оборота на этот SKU",
        ),
        sa.Column("net_benefit_rub", sa.Numeric(14, 2), nullable=True),
        sa.Column("payback_days", sa.Numeric(6, 1), nullable=True),
        # Контекст для алгоритма
        sa.Column("demand_14d_at_target", sa.Integer(), nullable=True),
        sa.Column("current_stock_at_target", sa.Integer(), nullable=True),
        sa.Column("current_stock_at_source", sa.Integer(), nullable=True),
        sa.Column("transit_days_estimated", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="pending/approved/dismissed/queued/executed/failed",
        ),
    )
    op.create_index(
        "idx_redistribution_recs_status",
        "redistribution_recommendations",
        ["tenant_id", "status", "generated_at"],
    )

    # ── 3. RedistributionTask ──────────────────────────────────────
    op.create_table(
        "redistribution_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "recommendation_id",
            sa.BigInteger(),
            sa.ForeignKey("redistribution_recommendations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_window_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Ближайшие 09:00 или 18:00 МСК",
        ),
        sa.Column("chrt_id", sa.BigInteger(), nullable=False),
        sa.Column("from_office_id", sa.BigInteger(), nullable=True),
        sa.Column("from_office_name", sa.String(128), nullable=False),
        sa.Column("to_office_id", sa.BigInteger(), nullable=False),
        sa.Column("to_office_name", sa.String(128), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Выше — раньше отправим в окне (по убыванию net_benefit)",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_response", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'queued'"),
            comment="queued/sent/accepted/rejected/failed/cancelled",
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transit_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_redistribution_tasks_window",
        "redistribution_tasks",
        ["tenant_id", "target_window_at", "status"],
    )

    # ── 4. RedistributionCooldown ──────────────────────────────────
    op.create_table(
        "redistribution_cooldowns",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chrt_id", sa.BigInteger(), nullable=False),
        sa.Column("to_office_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "cooldown_until",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="72ч после последней успешной заявки. Меньше → нельзя повторять.",
        ),
        sa.Column(
            "last_task_id",
            sa.BigInteger(),
            sa.ForeignKey("redistribution_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "chrt_id", "to_office_id"),
    )

    # ── 5. RedistributionRoiSnapshot ───────────────────────────────
    op.create_table(
        "redistribution_roi_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "revenue_total_rub",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
            comment="Выручка периода (для расчёта +0.5% комиссии)",
        ),
        sa.Column(
            "redistribution_fee_rub",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
            comment="+0.5% от выручки — что мы заплатили WB",
        ),
        sa.Column(
            "logistics_saving_rub",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
            comment="Оценка экономии на логистике",
        ),
        sa.Column("il_avg_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("il_delta_30d_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "successful_tasks_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "failed_tasks_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("estimated_revenue_uplift_rub", sa.Numeric(14, 2), nullable=True),
        sa.UniqueConstraint("tenant_id", "snapshot_date", name="uq_roi_snapshot_day"),
    )


def downgrade() -> None:
    op.drop_table("redistribution_roi_snapshots")
    op.drop_table("redistribution_cooldowns")
    op.drop_index("idx_redistribution_tasks_window", table_name="redistribution_tasks")
    op.drop_table("redistribution_tasks")
    op.drop_index("idx_redistribution_recs_status", table_name="redistribution_recommendations")
    op.drop_table("redistribution_recommendations")
    op.drop_table("wb_lk_sessions")
