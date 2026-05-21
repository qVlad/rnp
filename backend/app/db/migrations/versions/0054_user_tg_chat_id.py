"""users.tg_chat_id — per-user Telegram binding (multi-recipient broadcast).

Раньше TG-нотификации (supply→TG / plan_edit_request) шли в один-единственный
`AppSetting.tg_chat_id` тенанта — обычно chat первого директора который
сделал /start. Теперь каждый юзер может привязать свой chat → fan-out
рассылки на всех директоров.

`tg_chat_id` NULL = юзер не привязал Telegram. Бот ставит его через /start
если пользователь авторизовался (`/login <username>` команда — добавим
follow-up'ом). Пока что: значение либо ставится напрямую через UI
(/settings → «Подключить Telegram»), либо унаследуется из AppSetting.

Revision ID: 0054
Revises: 0053
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tg_chat_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_users_tg_chat_id", "users", ["tg_chat_id"])


def downgrade() -> None:
    op.drop_index("ix_users_tg_chat_id", table_name="users")
    op.drop_column("users", "tg_chat_id")
