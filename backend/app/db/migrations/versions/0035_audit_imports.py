"""Audit-режим v1 — таблицы audit_imports + audit_decisions.

Реализация LEAD-006 (см. agents/references/spec-audit-mode.md). Хранит:
- audit_imports: загруженные XLSX от пользователя (WB-кабинет / бухгалтер)
  в нормализованном JSON-формате. Один период × один источник = одна строка
  (UNIQUE constraint).
- audit_decisions: принятые решения по строкам с расхождением Δ > 0.01₽
  ("принять наш / WB / бух") — отдельный журнал, дополняет общий audit_log.

Решение собственника: гибрид XLSX-import в v1 → API в v2.

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-18 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_imports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            comment="'wb_cabinet' | 'bookkeeper' — источник XLSX",
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "file_name",
            sa.String(255),
            nullable=True,
            comment="Оригинальное имя загруженного файла (для UI)",
        ),
        sa.Column(
            "rows_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Сколько строк XLSX было обработано",
        ),
        sa.Column(
            "data_json",
            JSONB(),
            nullable=False,
            comment="Нормализованные строки: {lines: [{code, label, amount}], raw_meta: {...}}",
        ),
        sa.Column(
            "mapping_json",
            JSONB(),
            nullable=True,
            comment="Для bookkeeper: маппинг колонок XLSX → canonical line_code",
        ),
        sa.Column("imported_by", sa.String(64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source",
            "period_start",
            "period_end",
            name="uq_audit_import",
        ),
    )
    op.create_index(
        "idx_audit_imports_period",
        "audit_imports",
        ["tenant_id", "period_start", "period_end"],
    )

    op.create_table(
        "audit_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "line_code",
            sa.String(64),
            nullable=False,
            comment="Канонический код строки ОПиУ (revenue_gross, commission_wb, …)",
        ),
        sa.Column(
            "chosen_source",
            sa.String(32),
            nullable=False,
            comment="'ours' | 'wb_cabinet' | 'bookkeeper' — какую цифру принимаем",
        ),
        sa.Column("delta_ours_wb", sa.Numeric(14, 2), nullable=True),
        sa.Column("delta_ours_bk", sa.Numeric(14, 2), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_audit_decisions_period",
        "audit_decisions",
        ["tenant_id", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("idx_audit_decisions_period", table_name="audit_decisions")
    op.drop_table("audit_decisions")
    op.drop_index("idx_audit_imports_period", table_name="audit_imports")
    op.drop_table("audit_imports")
