from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.api import (
    analytics,
    artificial_orders,
    audit,
    auth as auth_api,
    brands,
    calc,
    cash_flow,
    cost_history,
    dashboard,
    excel,
    external_ad_costs,
    off_platform,
    opex,
    plans,
    pnl,
    product_groups,
    products,
    settings,
    units,
    users,
    wb_token,
)
from app.core.config import settings as cfg
from app.core.logging import configure_logging, get_logger
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


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Require a valid session cookie on every /api/* request except the
    explicitly-public ones (login, bootstrap, health, whoami).

    Per-handler `get_current_user` dependency does the full DB lookup with
    role + active-flag checks; this middleware just enforces "have a token"
    so anonymous users get 401 immediately without hitting handler code.
    """
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS:
        return await call_next(request)
    token = request.cookies.get(cfg.auth_cookie_name)
    if not token or not decode_session_token(token):
        return JSONResponse(
            {"detail": "not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/whoami")
async def whoami() -> dict[str, object]:
    return {
        "app": cfg.app_name,
        "debug": cfg.debug,
        "wb_token_configured": bool(cfg.wb_token),
        "history_days_on_first_run": cfg.history_days_on_first_run,
    }


app.include_router(dashboard.router)
app.include_router(pnl.router)
app.include_router(units.router)
app.include_router(settings.router)
app.include_router(artificial_orders.router)
app.include_router(external_ad_costs.router)
app.include_router(opex.router)
app.include_router(cost_history.router)
app.include_router(analytics.router)
app.include_router(plans.router)
app.include_router(cash_flow.router)
app.include_router(calc.router)
app.include_router(products.router)
app.include_router(wb_token.router)
app.include_router(excel.router)
app.include_router(off_platform.router)
app.include_router(product_groups.router)
app.include_router(audit.router)
app.include_router(auth_api.router)
app.include_router(users.router)
app.include_router(brands.router)
