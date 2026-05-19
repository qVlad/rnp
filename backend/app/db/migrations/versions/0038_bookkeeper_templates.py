"""Сохраняемые шаблоны маппинга колонок бухгалтерского XLSX (LEAD-015).

Persona-Accountant review: без шаблонов бухгалтер бросит audit-mode после
2-го использования (каждый раз настраивать маппинг колонок руками = ~10
минут на загрузку). С шаблоном — 1 клик.

Mapping_json структура идентична audit_imports.mapping_json — wide/long
формат, sheet, column_to_code, etc.

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bookkeeper_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "name",
            sa.String(128),
            nullable=False,
            comment="User-defined имя шаблона ('Контур', '1С Стас', и т.п.)",
        ),
        sa.Column(
            "mapping_json",
            JSONB(),
            nullable=False,
            comment="Идентично audit_imports.mapping_json — wide/long + column_to_code",
        ),
        sa.Column("created_by", sa.String(64), nullable=False),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_bookkeeper_template_name"),
    )


def downgrade() -> None:
    op.drop_table("bookkeeper_templates")
