import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.deps import LoginRequired, login_redirect_handler
from app.routers import (
    account_misc,
    accounts,
    admin,
    api_v1,
    auth,
    billing,
    dashboard,
    public,
    settings_bot,
    trading,
    webhooks,
)
from app.templating import templates

async def _sweeper_loop():
    from app.services.sweeper import run_sweep

    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                run_sweep(db)
            finally:
                db.close()
        except Exception:  # never let the watchdog die
            logging.getLogger("brotherbot.sweeper").exception("sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.env)
        except ImportError:
            logging.getLogger("brotherbot").warning("BB_SENTRY_DSN set but sentry-sdk not installed")
    task = asyncio.create_task(_sweeper_loop()) if settings.sweeper_enabled else None
    yield
    if task:
        task.cancel()


# [SEC 08-01] fail fast: never boot production on shipped default secrets.
get_settings().assert_secure_for_production()

app = FastAPI(
    title="Brother Bot Platform",
    version="1.1.0",
    docs_url="/api/docs" if not get_settings().is_production else None,
    lifespan=lifespan,
)

init_db()

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.add_exception_handler(LoginRequired, login_redirect_handler)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if get_settings().is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """Browser form CSRF defence: state-changing requests must come from our
    own origin. Cookies are SameSite=Lax as the first line; this catches the
    rest. API and webhook clients (no Origin header, token-authenticated)
    are unaffected."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.url.path.startswith(("/api/", "/webhooks/")):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            from urllib.parse import urlparse

            origin_host = urlparse(origin).netloc.split(":")[0]
            our_hosts = {request.url.hostname, urlparse(get_settings().base_url).netloc.split(":")[0]}
            if origin_host not in our_hosts:
                return HTMLResponse("Cross-origin request rejected", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def maintenance_gate(request: Request, call_next):
    """Super-admin maintenance mode: public + admin + webhooks stay reachable."""
    path = request.url.path
    exempt = path.startswith(("/admin", "/login", "/logout", "/static", "/webhooks", "/api/"))
    if not exempt:
        from app.models.platform import SystemSetting

        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter_by(key="maintenance_mode").first()
            if row and row.value == "on":
                return HTMLResponse(
                    "<h1 style='font-family:sans-serif;text-align:center;margin-top:20vh'>"
                    "🔧 Brother Bot is under maintenance</h1>"
                    "<p style='text-align:center;font-family:sans-serif'>We'll be back shortly.</p>",
                    status_code=503,
                )
        finally:
            db.close()
    return await call_next(request)


for module in (public, auth, dashboard, accounts, settings_bot, trading,
               billing, account_misc, admin, api_v1, webhooks):
    app.include_router(module.router)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith(("/api/", "/webhooks/")):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Not found"}, status_code=404)
    return templates.TemplateResponse(request, "public/404.html", {"user": None}, status_code=404)


@app.get("/healthz")
def healthz():
    # Liveness only. Iron Rule 5: a 200 here proves the process is up, nothing more.
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Readiness: proves the database answers, not just that we're running."""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": True}
    finally:
        db.close()


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Prometheus text exposition — scrape with prometheus/grafana."""
    from datetime import timedelta

    from app.models.platform import Ticket, WebhookLog
    from app.models.trading import MT5Account, Signal, Trade
    from app.models.user import User, UserSession, utcnow

    db = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(minutes=5)
        values = {
            "brotherbot_users_total": db.query(User).count(),
            "brotherbot_sessions_active": db.query(UserSession)
                .filter(UserSession.last_seen_at >= cutoff, UserSession.revoked.is_(False)).count(),
            "brotherbot_mt5_accounts_total": db.query(MT5Account).count(),
            "brotherbot_mt5_accounts_online": db.query(MT5Account)
                .filter(MT5Account.last_heartbeat_at >= cutoff).count(),
            "brotherbot_signals_total": db.query(Signal).count(),
            "brotherbot_trades_open": db.query(Trade).filter_by(status="open").count(),
            "brotherbot_tickets_open": db.query(Ticket).filter_by(status="open").count(),
            "brotherbot_webhook_errors_total": db.query(WebhookLog)
                .filter(WebhookLog.status_code >= 400).count(),
        }
        return "\n".join(f"{k} {v}" for k, v in values.items()) + "\n"
    finally:
        db.close()
