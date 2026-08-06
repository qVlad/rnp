from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SellerFriends"
    debug: bool = False

    # Git commit hash (короткий) — подставляется `./scripts/remote.sh deploy`
    # как `git rev-parse --short HEAD`. Локально без deploy — 'dev'.
    app_version: str = "dev"
    # SemVer (что катим, source of truth — `/VERSION`). Подставляется deploy-скриптом.
    # В UI бейдж показывает `v{app_semver} · {app_version}`.
    app_semver: str = "dev"
    # Дата сборки/деплоя (ISO 8601). Подставляется deploy-скриптом.
    build_time: str = ""

    database_url: str = Field(
        default="postgresql+asyncpg://app:app@postgres:5432/rnp",
        description="Async DSN for application code",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://app:app@postgres:5432/rnp",
        description="Sync DSN for Alembic and Celery",
    )
    redis_url: str = "redis://redis:6379/0"

    wb_token: str | None = None
    wb_statistics_base: str = "https://statistics-api.wildberries.ru"
    wb_advert_base: str = "https://advert-api.wildberries.ru"
    # common-api is not a real WB host; Content API is suppliers-api or content-api.
    # We keep this as a fallback base for any misc endpoints we might add.
    wb_common_base: str = "https://common-api.wildberries.ru"  # WB_API_REFERENCE §2
    # Future-dated hosts for sunset migrations (see WB_API_REFERENCE §9):
    #   /supplier/stocks         → 2026-06-23 → seller-analytics-api
    #   /reportDetailByPeriod    → 2026-07-15 → finance-api
    wb_analytics_base: str = "https://seller-analytics-api.wildberries.ru"
    wb_finance_base: str = "https://finance-api.wildberries.ru"
    wb_content_base: str = "https://content-api.wildberries.ru"
    # discounts-prices-api: /api/v2/list/goods/filter (TASK-LEAD-074).
    # Sandbox: discounts-prices-api-sandbox.wildberries.ru.
    wb_prices_base: str = "https://discounts-prices-api.wildberries.ru"
    # marketplace-api: FBS/DBS — сборочные задания, поставки, склады продавца,
    # остатки FBS (TASK-DEV-098). Sandbox: marketplace-api-sandbox.wildberries.ru.
    wb_marketplace_base: str = "https://marketplace-api.wildberries.ru"

    # Rate limits:
    # Statistics (statistics-api.wildberries.ru):
    #   Observed in production: x-ratelimit-limit=1, penalty ~2.3 hours after burst.
    #   Personal token limit: 1 req/min sustained is safe; WB applies a short burst
    #   allowance (around 3-5 req in quick succession) before the penalty kicks in.
    #   Keep at 1 req/min to never trigger the burst window.
    wb_stats_rate_per_min: int = 1
    # Advert (advert-api.wildberries.ru):
    #   /adv/v1/promotion/count: documented 1 req/min
    #   /adv/v2/promotion/adverts: ~1 req/s
    #   /adv/v3/fullstats (replaces /adv/v2/fullstats since 2025-10): documented
    #     limit is 3 req/min (interval ~20s) for both Personal and Service tokens.
    #   The bottleneck is fullstats — keep the global limiter at 3/min so a
    #   batched run of /adv/v3/fullstats chunks does not race past the limit.
    #   Other advert endpoints are syncs are infrequent (hourly), so the lower
    #   ceiling is not a problem.
    wb_advert_rate_per_min: int = 3
    wb_request_timeout: float = 60.0

    history_days_on_first_run: int = 90
    timezone: str = "Europe/Moscow"

    # Telegram bot (optional). Token is created via @BotFather and put into .env.
    # Once set, the `bot` service starts long-polling and the Celery beat-scheduled
    # digest task delivers daily summaries.
    tg_bot_token: str | None = None
    # Tenant the bot pins itself to. In the current single-seller deployment the
    # default tenant_id=1 is correct. A future multi-bot setup will need
    # per-tenant tokens or chat→tenant routing.
    bot_tenant_id: int = 1

    # ── Authentication / JWT ──────────────────────────────────────────────
    # SECRET used to sign JWT cookies. **MUST be set in .env** in production
    # — fallback below is for development only and will trigger a startup
    # warning. Rotating this invalidates all active sessions.
    jwt_secret_key: str = "dev-only-CHANGE-ME-in-.env-please-make-it-long-and-random"
    jwt_algorithm: str = "HS256"
    # Session lifetime — short enough to limit damage if someone forgets to
    # log out, long enough not to annoy daily users.
    jwt_expires_hours: int = 12
    # HttpOnly cookie name. Must match in client (sent automatically) and
    # server (`Cookie:` header parsing).
    auth_cookie_name: str = "rnp_session"
    # Mark cookie `Secure` when serving over HTTPS. Localhost dev = False.
    auth_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
