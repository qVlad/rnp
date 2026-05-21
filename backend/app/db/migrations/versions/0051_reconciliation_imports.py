"""reconciliation_imports — таблица импортированных XLSX от бухгалтера.

Закрывает 4-ю колонку Reconciliation 4-way UI. До этого колонка
«Бухгалтер» в `/reconciliation/4way` была заглушкой (`available=false`).

Теперь:
- Бухгалтер выгружает из 1С недельную/месячную сводку в XLSX
- Юзер аплоадит на /reconciliation-4way через UI
- Парсер `services/reconciliation_import.py` извлекает суммы по периодам
- В таблицу UPSERT по (tenant_id, source, period_from, period_to)
- 4-way endpoint подмешивает значения в `bookkeeper.*`
- На UI 4-я колонка заполняется + дельта-подсветка vs наш P&L и WB

`source` enum-like (varchar): сейчас только 'bookkeeper', но в будущем можно
расширить ('wb_cabinet_manual' — для ручной выгрузки ЛК WB если sync упал, etc.).

Revision ID: 0051
Revises: 0050
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_imports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("revenue_gross_rub", sa.Numeric(14, 2)),
        sa.Column("revenue_returns_rub", sa.Numeric(14, 2)),
        sa.Column("commission_rub", sa.Numeric(14, 2)),
        sa.Column("payout_rub", sa.Numeric(14, 2)),
        # Опциональный комментарий (от бухгалтера, или auto: имя файла + период)
        sa.Column("note", sa.Text()),
        sa.Column("filename", sa.String(255)),
        sa.Column(
            "imported_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "source", "period_from", "period_to",
            name="uq_recon_imports_tenant_source_period",
        ),
    )
    op.create_index(
        "ix_recon_imports_tenant_period",
        "reconciliation_imports",
        ["tenant_id", "period_from", "period_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_recon_imports_tenant_period", table_name="reconciliation_imports")
    op.drop_table("reconciliation_imports")
