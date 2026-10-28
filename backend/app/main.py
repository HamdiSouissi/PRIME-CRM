from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os, time
from .config import settings
from .database import init_db, SessionLocal
from .models.company import Company
from .models.user import User
from .models.stage import PipelineStage
from .routers import auth, users, clients, stages, opportunities, activities, products, quotes, dashboard, imports_exports, ai, admin

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Prime CRM - CRM intelligent pour TPE/PME par Prime Vision Solutions. API REST documentée OpenAPI.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS - must be permissive for preview host e2b.app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting simple: track attempts per IP for login
from collections import defaultdict
login_attempts = defaultdict(list)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    # Security headers
    start = time.time()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Process-Time"] = str(time.time() - start)
    return response

@app.on_event("startup")
def on_startup():
    init_db()
    # Seed default data if empty
    db = SessionLocal()
    try:
        # Ensure admin exists if no users
        from .core.security import get_password_hash
        from datetime import datetime, timezone
        if db.query(User).count() == 0:
            print("Création du compte admin par défaut...")
            company = Company(name=settings.FIRST_SUPERUSER_COMPANY, slug="prime-vision-solutions", email=settings.FIRST_SUPERUSER_EMAIL)
            db.add(company)
            db.flush()
            user = User(
                email=settings.FIRST_SUPERUSER_EMAIL,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                first_name="Admin",
                last_name="Prime",
                role="admin",
                is_superuser=True,
                company_id=company.id
            )
            db.add(user)
            db.commit()
            # stages
            DEFAULT_STAGES = [
                {"name": "Nouveau prospect", "color": "#64748b", "order": 1},
                {"name": "Premier contact", "color": "#0ea5e9", "order": 2},
                {"name": "Qualification", "color": "#8b5cf6", "order": 3},
                {"name": "Rendez-vous programmé", "color": "#f59e0b", "order": 4},
                {"name": "Proposition commerciale", "color": "#ec4899", "order": 5},
                {"name": "Négociation", "color": "#f97316", "order": 6},
                {"name": "Gagné", "color": "#22c55e", "order": 7, "is_won": True},
                {"name": "Perdu", "color": "#ef4444", "order": 8, "is_lost": True},
            ]
            for s in DEFAULT_STAGES:
                stage = PipelineStage(company_id=company.id, name=s["name"], color=s["color"], order=s["order"], is_won=s.get("is_won", False), is_lost=s.get("is_lost", False))
                db.add(stage)
            db.commit()
            print(f"Admin créé: {settings.FIRST_SUPERUSER_EMAIL} / {settings.FIRST_SUPERUSER_PASSWORD}")
    except Exception as e:
        print(f"Startup error: {e}")
    finally:
        db.close()
    
    # ensure upload dir
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# Routers
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
        "message": "Prime CRM API - Propulsé par Prime Vision Solutions"
    }

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": settings.VERSION}

@app.get("/api/v1/health", tags=["health"])
def health_v1():
    return {"status": "ok", "version": settings.VERSION}

# Global exception handler to avoid leaking secrets
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Don't expose internal details for 500
    import traceback
    print(f"Unhandled error on {request.url}: {exc}")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})
