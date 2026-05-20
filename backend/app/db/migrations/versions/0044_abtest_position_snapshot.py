"""Снимки позиций A/B-тестовых карточек в выдаче WB (поисковая / каталог).

Цель — помочь объяснить дисперсию показов между вариантами A/B-теста: если фото
A было на 1-й странице, а B на 4-й — разница в трафике не от фото, а от
позиции в SEO. Данные собирает Chrome-расширение (companion-MV3 в
`extension/src/content/wb-search.ts`) при заходе юзера на www.wildberries.ru
с включенным флагом `enablePositionTracking`.

Один INSERT — один снимок: nmId × запрос × позиция × страница × момент времени.
Дедуп **не делаем** — частота важна для оценки стабильности позиции (если
позиция шатает 8→12→6 за 5 минут — это очень разные ситуации).

Хранение бессрочное (TTL отсутствует) — корреляция «позиция при показах
варианта A» нужна на горизонте 7-30 дней теста. Если объём станет проблемой —
добавить отдельный partition / TTL job (см. ROADMAP).

См. `backend/app/api/extension.py` (POST /positions) и
`extension/src/content/wb-search.ts`.

Revision ID: 0044
Revises: 0043
Create Date: 2026-05-19 22:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "abtest_position_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "nm_id",
            sa.BigInteger(),
            nullable=False,
            comment="WB nmId карточки",
        ),
        sa.Column(
            "query",
            sa.String(500),
            nullable=False,
            comment="Поисковый запрос или URL каталога — что юзер открыл",
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            comment="Позиция карточки в выдаче (1-based)",
        ),
        sa.Column(
            "page",
            sa.Integer(),
            nullable=False,
            comment="Номер страницы (1-based; на /search.aspx первая = 1)",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="ISO timestamp с extension (от пользователя — приходит как строка)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Композитные индексы для типичных запросов UI:
    #   • история позиций конкретного nm — фильтр по nm + сортировка по дате
    #   • «по какому запросу позиция шатается» — фильтр по query + сортировка по дате
    op.create_index(
        "ix_abtest_pos_tenant_nm_dt",
        "abtest_position_snapshot",
        ["tenant_id", "nm_id", "collected_at"],
    )
    op.create_index(
        "ix_abtest_pos_tenant_q_dt",
        "abtest_position_snapshot",
        ["tenant_id", "query", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_abtest_pos_tenant_q_dt", table_name="abtest_position_snapshot")
    op.drop_index("ix_abtest_pos_tenant_nm_dt", table_name="abtest_position_snapshot")
    op.drop_table("abtest_position_snapshot")
