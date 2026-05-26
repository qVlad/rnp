"""users.boss_id — manager → ROP delivery для TG-share (HYP-007).

Manager жмёт «📨 в Telegram» в /weekly-report → отчёт улетает ему в личку
(`User.tg_chat_id`). Warn-плашка объясняла «попроси РОПа», но не решала
проблему. Теперь: если у manager'а есть `boss_id` (его непосредственный
руководитель, обычно head_of_sales или director), TG-share при `recipient=self`
приоритетно отправляет отчёт на `boss.tg_chat_id`, fallback на свой.

Self-FK с `ondelete='SET NULL'` — если руководителя удалили, manager не
ломается, просто переключается на fallback (свой tg_chat_id).

API: `PUT /api/users/{user_id}/boss` body `{boss_id: int | null}` (director-only)
для назначения. Cycle detection в endpoint'е.

Revision ID: 0062
Revises: 0061
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("boss_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_boss_id",
        "users",
        "users",
        ["boss_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_boss_id", "users", ["boss_id"])


def downgrade() -> None:
    op.drop_index("ix_users_boss_id", table_name="users")
    op.drop_constraint("fk_users_boss_id", "users", type_="foreignkey")
    op.drop_column("users", "boss_id")
