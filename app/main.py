from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from app.api.router import api_router
from app.api.routes import troubleshooting
from app.api.routes.alarms import router as alarms_router
from app.api.routes.auth_frontend import router as frontend_auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.logs import router as logs_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.reports import router as reports_router
from app.api.routes.settings import router as settings_router
from app.core.auth import get_current_user_from_session, is_admin_user
from app.core.config import (
    CORS_ALLOWED_ORIGINS,
    SECRET_KEY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    SESSION_MAX_AGE,
)
from app.db.session import get_db
from app.routes.auth import router as auth_router

app = FastAPI(title="Service Performance Monitoring System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=SESSION_MAX_AGE,
    same_site=SESSION_COOKIE_SAMESITE,
    https_only=SESSION_COOKIE_SECURE,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

def redirect_to_signin():
    return RedirectResponse(url="/signin", status_code=303)

@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_well_known():
    return Response(status_code=204)

@app.get("/")
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)

    if not current_user:
        return redirect_to_signin()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)

    if not current_user:
        return redirect_to_signin()

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )

@app.get("/logs")
def logs_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)

    if not current_user:
        return redirect_to_signin()

    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )

@app.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)

    if not current_user:
        return redirect_to_signin()

    if not is_admin_user(current_user):
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )

app.include_router(auth_router)
app.include_router(api_router, prefix="/api")
app.include_router(frontend_auth_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(alarms_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(troubleshooting.router, prefix="/api")