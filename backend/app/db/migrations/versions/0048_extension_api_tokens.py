"""extension_api_tokens — long-lived токены для Chrome-расширения.

JWT в cookie `rnp_session` имеет TTL 12 часов — расширение приходилось
переподключать ежедневно. Эта таблица хранит отдельные opaque-токены
формата `rnpext_<32-hex>` с настраиваемым/бесконечным сроком жизни и
возможностью revoke.

Структура:
- `token_hash` (sha256 hex) для быстрого lookup в `_user_from_bearer`
- `prefix` (первые 12 символов токена) для UI: «rnpext_abc12345…»
- `expires_at` NULL = без срока
- `revoked_at` NULL = активен

Revision ID: 0048
Revises: 0047
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extension_api_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_extension_api_tokens_user_id",
        "extension_api_tokens",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extension_api_tokens_user_id",
        table_name="extension_api_tokens",
    )
    op.drop_table("extension_api_tokens")
