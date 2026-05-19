"""LEAD-014: claim_templates — шаблоны текстов претензий для chargebacks.

Persona-Manager review: я пишу одинаковую претензию для штрафов
«Логистика < 100₽» по 20 раз в месяц. Хочу: выбрать шаблон → авто-заполнить
`claim_text` в expand-row.

Persona-Accountant: тот же кейс для разбора удержаний / коррекций.

Структура: `(tenant_id, category, name)` UNIQUE. Один шаблон может быть
«дефолтным» для категории (`is_default=true`) — при ручном заполнении
claim_text у нового chargeback автоматически предлагается дефолт.

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-19 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category",
            sa.String(32),
            nullable=False,
            comment="Категория chargeback (penalty/deduction/etc.) — см. OPER_NAME_TO_CATEGORY",
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "template_text",
            sa.Text(),
            nullable=False,
            comment="Текст шаблона. Может содержать плейсхолдеры {amount}, {rrd_id}, {nm_id} которые подставит фронт.",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Дефолт для категории. UI авто-заполнит при создании нового chargeback того же типа.",
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
        sa.UniqueConstraint(
            "tenant_id", "category", "name", name="uq_claim_template_name"
        ),
    )
    op.create_index(
        "idx_claim_templates_default",
        "claim_templates",
        ["tenant_id", "category", "is_default"],
    )


def downgrade() -> None:
    op.drop_index("idx_claim_templates_default", table_name="claim_templates")
    op.drop_table("claim_templates")
