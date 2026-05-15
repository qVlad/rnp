"""Джем: поисковые запросы и кластеры (10X-методика).

Две таблицы:
  jam_queries  — сырые поисковые запросы по SKU (sync с WB Jam API когда
                 будет подписка; пока заполняется через Excel-импорт юзером
                 вручную из «Аналитики сравнения карточек» WB-кабинета).
  jam_clusters — производное кеш с агрегатами по кластеру (готовые цифры
                 для UI: orders, clicks, conv%, MAX CPC и т.д.). Можно
                 пересчитывать в момент запроса (для текущего объёма данных
                 этого хватит) — таблица оставлена как опциональный кеш.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-15 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jam_queries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False, index=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ad_spent", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_jam_queries_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id", "nm_id", "query", "period_start",
            name="uq_jam_queries_tenant_nm_query_period",
        ),
    )
    op.create_index(
        "ix_jam_queries_tenant_nm",
        "jam_queries",
        ["tenant_id", "nm_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_jam_queries_tenant_nm", table_name="jam_queries")
    op.drop_table("jam_queries")
