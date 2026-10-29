import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings

# Validate before constructing a database engine or importing API routers.
# Alembic imports the configuration but does not import this module.
settings.validate_runtime()

from .database import SessionLocal
from .models.user import User
from .schema import require_current_schema
from .services.redis_store import get_redis_store
from .routers import activities, admin, ai, auth, clients, dashboard, imports_exports, opportunities, products, quotes, stages, users


logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Prime CRM - CRM intelligent pour TPE/PME par Prime Vision Solutions. API REST documentée OpenAPI.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith(f"{settings.API_V1_STR}/auth/"):
        # Authentication responses must not be retained by shared caches.
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Process-Time"] = str(time.time() - start)
    return response


@app.on_event("startup")
def on_startup():
    # Do not create or mutate the schema here: Alembic owns schema changes.
    try:
        with SessionLocal() as db:
            require_current_schema(db)
            has_users = db.query(User.id).first() is not None
    except Exception:
        # Driver errors and SQL details may contain database credentials.
        raise RuntimeError("Base inaccessible ou migrations non appliquées") from None

    if not has_users and not settings.ALLOW_PUBLIC_REGISTRATION:
        raise RuntimeError("Aucun utilisateur : initialisez d'abord le premier administrateur")

    try:
        store = get_redis_store()
        if store is not None:
            store.check_writable()
        elif settings.APP_ENV == "production":
            raise RuntimeError("Redis est requis")
    except Exception:
        # Connection errors may include the Redis URL and its credentials.
        raise RuntimeError("Redis inaccessible ou non disponible en écriture") from None

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@app.on_event("shutdown")
def close_redis_connections():
    try:
        store = get_redis_store()
        if store is not None:
            store.close()
    except Exception:
        logger.warning("Could not close Redis connections cleanly")
    finally:
        get_redis_store.cache_clear()


app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(clients.router, prefix=settings.API_V1_STR)
app.include_router(stages.router, prefix=settings.API_V1_STR)
app.include_router(opportunities.router, prefix=settings.API_V1_STR)
app.include_router(activities.router, prefix=settings.API_V1_STR)
app.include_router(products.router, prefix=settings.API_V1_STR)
app.include_router(quotes.router, prefix=settings.API_V1_STR)
app.include_router(dashboard.router, prefix=settings.API_V1_STR)
app.include_router(imports_exports.router, prefix=settings.API_V1_STR)
app.include_router(ai.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)


@app.get("/", tags=["health"])
def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "ok",
        "docs": "/docs",
        "message": "Prime CRM API - Propulsé par Prime Vision Solutions",
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": settings.VERSION}


@app.get("/api/v1/health", tags=["health"])
def health_v1():
    return {"status": "ok", "version": settings.VERSION}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic's default error includes the rejected input, sometimes the whole
    # request body. Never echo a password from an authentication/account form.
    sensitive_paths = {
        f"{settings.API_V1_STR}/auth/login",
        f"{settings.API_V1_STR}/auth/login-json",
        f"{settings.API_V1_STR}/auth/register",
        f"{settings.API_V1_STR}/auth/change-password",
        f"{settings.API_V1_STR}/users",
    }
    route_path = getattr(request.scope.get("route"), "path", "")
    if request.method == "POST" and route_path in sensitive_paths:
        return JSONResponse(status_code=422, content={"detail": "Données invalides"})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Do not log request URLs, query strings, bodies, exception messages or
    # tracebacks: these can contain credentials. The route template is safe.
    route = request.scope.get("route")
    route_path = getattr(route, "path", "<unknown>")
    logger.error("Unhandled %s on route %s", type(exc).__name__, route_path)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})
