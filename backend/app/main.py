from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.api import (
    abtest,
    abtest_uploads,
    ads,
    analytics,
    artificial_orders,
    audit,
    audit_mode,
    auth as auth_api,
    brands,
    calc,
    cash_flow,
    chargebacks,
    checklist,
    cost_history,
    dashboard,
    dashboard_compare,
    excel,
    extension,
    extension_lk_jobs,
    external_ad_costs,
    features_doc,
    user_guide_doc,
    funnel,
    inventory,
    jam,
    localization,
    managers_kpi,
    metric_templates,
    notifications,
    off_platform,
    opex,
    plan_edit_requests,
    plans,
    pnl,
    product_groups,
    product_tags,
    products,
    promo_calculator,
    reconciliation_4way,
    redistribution,
    season_plan,
    settings,
    supplies,
    supply_send,
    sync_status,
    tariffs,
    tax_report,
    tenant_modules,
    tenant_settings,
    unit_plan,
    units,
    users,
    view_presets,
    wb_token,
)
from app.core.config import settings as cfg
from app.core.logging import configure_logging, get_logger
from app.services.active_tenant import active_tenant_middleware
from app.services.auth import PUBLIC_PATHS, decode_session_token

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("Starting %s (debug=%s)", cfg.app_name, cfg.debug)
    if cfg.jwt_secret_key.startswith("dev-only-CHANGE-ME"):
        log.warning(
            "⚠ JWT_SECRET_KEY is the dev-default. Set a real value in .env "
            "(e.g. `python3 -c 'import secrets; print(secrets.token_urlsafe(64))'`) "
            "before exposing this service beyond localhost. Using the default "
            "means anyone who reads the code can forge sessions."
        )

    # Multi-tenant миграция: если в .env задан WB_TOKEN, а у default tenant
    # (id=1) его ещё нет в БД — копируем. Это одноразовая миграция legacy
    # установки в новую multi-tenant схему.
    if cfg.wb_token:
        from app.db.models import Tenant  # noqa: WPS433
        from app.db.session import session_scope  # noqa: WPS433
        from app.services.secrets_crypto import encrypt  # noqa: WPS433
        from datetime import datetime, timezone  # noqa: WPS433

        async with session_scope() as s:
            tenant = await s.get(Tenant, 1)
            if tenant is not None and not tenant.wb_token:
                tenant.wb_token = encrypt(cfg.wb_token)
                tenant.wb_token_validated_at = datetime.now(timezone.utc)
                log.info("Migrated WB_TOKEN from .env to tenants.id=1")

    # Fernet migration: если SECRETS_ENCRYPTION_KEY задан, шифруем все
    # plaintext-токены в БД. Идемпотентно (no-op если уже зашифровано).
    from app.services.secrets_crypto import migrate_plaintext_tokens  # noqa: WPS433
    n = await migrate_plaintext_tokens()
    if n:
        log.info("Encrypted %d plaintext WB-tokens at startup", n)

    yield


app = FastAPI(
    title=cfg.app_name,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# Multi-cabinet (TASK-LEAD-048): active-tenant middleware.
# ORDER NOTE: в FastAPI/Starlette `@app.middleware("http")` декораторы
# складываются так что ПОСЛЕДНИЙ добавленный — внешний (запускается первым
# на request, последним на response). Поэтому `active_tenant_middleware`
# объявлен ДО `auth_gate` — значит на request `auth_gate` отрабатывает
# первым (проверяет cookie), потом `active_tenant_middleware` резолвит
# `request.state.active_tenant_id`.
app.middleware("http")(active_tenant_middleware)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Require a valid session cookie on every /api/* request except the
    explicitly-public ones (login, bootstrap, health, whoami).

    Per-handler `get_current_user` dependency does the full DB lookup with
    role + active-flag checks; this middleware just enforces "have a token"
    so anonymous users get 401 immediately without hitting handler code.
    """
    path = request.url.path
    # Public: explicit list + WB photo proxy (so <img> tags work without
    # sending cookie). Photo endpoint is read-only and only proxies WB CDN
    # which is itself public.
    if (
        not path.startswith("/api/")
        or path in PUBLIC_PATHS
        or (path.startswith("/api/products/") and path.endswith("/photo"))
    ):
        return await call_next(request)
    # /api/extension/* — companion Chrome-расширение шлёт `Authorization: Bearer
    # <jwt>` (cookie не доступна в MV3 service worker). Контракт строго Bearer-
    # only — endpoint'ы внутри сами валидируют через get_extension_user. Здесь
    # просто пропускаем middleware-проверку cookie, чтобы не возвращать 401
    # ещё до handler'а.
    if path.startswith("/api/extension/"):
        return await call_next(request)
    token = request.cookies.get(cfg.auth_cookie_name)
    # Универсальный fallback: Authorization: Bearer <jwt>. Удобно для CLI и
    # внешних интеграций. Сам по себе не предоставляет привилегий — handler
    # потом ещё раз проверит токен через get_current_user (cookie-only).
    # Поэтому реальный путь для не-cookie клиентов — через /api/extension/*.
    if not token or not decode_session_token(token):
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            if decode_session_token(bearer):
                return await call_next(request)
        return JSONResponse(
            {"detail": "not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/version")
async def version() -> dict[str, str]:
    """Версия сервиса (git short hash + дата сборки/деплоя).

    Подставляется скриптом `./scripts/remote.sh deploy` через env-переменные
    APP_VERSION и BUILD_TIME. UI забирает один раз при загрузке и показывает
    в нижнем правом углу.
    """
    return {
        "version": cfg.app_version,
        "build_time": cfg.build_time,
        "name": cfg.app_name,
    }


@app.get("/api/whoami")
async def whoami() -> dict[str, object]:
    return {
        "app": cfg.app_name,
        "debug": cfg.debug,
        "wb_token_configured": bool(cfg.wb_token),
        "history_days_on_first_run": cfg.history_days_on_first_run,
    }


app.include_router(dashboard.router)
app.include_router(dashboard_compare.router)
app.include_router(pnl.router)
app.include_router(units.router)
app.include_router(unit_plan.router)
app.include_router(ads.router)
app.include_router(view_presets.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(artificial_orders.router)
app.include_router(external_ad_costs.router)
app.include_router(opex.router)
app.include_router(cost_history.router)
app.include_router(analytics.router)
app.include_router(plans.router)
app.include_router(plan_edit_requests.router)
app.include_router(cash_flow.router)
app.include_router(calc.router)
app.include_router(products.router)
app.include_router(wb_token.router)
app.include_router(excel.router)
app.include_router(off_platform.router)
app.include_router(product_groups.router)
app.include_router(product_tags.router)
app.include_router(audit.router)
app.include_router(auth_api.router)
app.include_router(users.router)
app.include_router(brands.router)
app.include_router(tenant_settings.router)
app.include_router(tenant_modules.router)
app.include_router(audit_mode.router)
app.include_router(chargebacks.router)
app.include_router(redistribution.router)
app.include_router(tax_report.router)
app.include_router(tariffs.router)
app.include_router(supplies.router)
app.include_router(supply_send.router)
app.include_router(checklist.router)
app.include_router(season_plan.router)
app.include_router(jam.router)
app.include_router(funnel.router)
app.include_router(inventory.router)
app.include_router(sync_status.router)
app.include_router(features_doc.router)
app.include_router(user_guide_doc.router)
app.include_router(abtest.router)
app.include_router(abtest_uploads.router)
app.include_router(extension.router)
app.include_router(extension_lk_jobs.router)
app.include_router(localization.router)
app.include_router(managers_kpi.router)
app.include_router(metric_templates.router)
app.include_router(promo_calculator.router)
app.include_router(reconciliation_4way.router)
