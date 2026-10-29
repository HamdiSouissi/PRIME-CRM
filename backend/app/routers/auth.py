from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..config import settings
from ..core.permissions import get_current_user
from ..core.security import (
    create_access_token,
    get_password_hash,
    is_acceptable_new_password,
    is_valid_session_nonce,
    new_session_nonce,
    verify_password,
)
from ..database import get_db
from ..models.company import Company
from ..models.stage import PipelineStage
from ..models.user import User
from ..schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..services.redis_store import LoginRateLimited, RedisStore, get_redis_store

router = APIRouter(prefix="/auth", tags=["auth"])

# Public, non-credential bcrypt hash, generated with the same work factor as
# newly created accounts. Never use its verification result for authentication.
_DUMMY_LOGIN_HASH = "$2b$12$VB2wA4RZVVH2quey0wxfguwmhnw1JFpwdRos4/wxqVB/WEgJGFrLO"

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


def ensure_default_stages(db: Session, company_id: int):
    existing = db.query(PipelineStage).filter(PipelineStage.company_id == company_id).first()
    if not existing:
        for s in DEFAULT_STAGES:
            stage = PipelineStage(
                company_id=company_id,
                name=s["name"],
                color=s["color"],
                order=s["order"],
                is_won=s.get("is_won", False),
                is_lost=s.get("is_lost", False),
            )
            db.add(stage)
        db.commit()


def _enforce_limit(identifier: str, store: RedisStore | None, *, password_change: bool) -> None:
    if len(identifier) > 320:
        raise HTTPException(status_code=400, detail="Identifiants invalides")
    if store is None:
        # Redis may be absent only in explicit development/test environments.
        if settings.APP_ENV == "production":
            raise HTTPException(status_code=503, detail="Service de sécurité temporairement indisponible")
        return
    try:
        if password_change:
            store.record_password_change(identifier)
        else:
            store.record_login(identifier)
    except LoginRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives. Réessayez plus tard.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except (RedisError, UnicodeError):
        # Never bypass a configured limiter when Redis is unavailable.
        raise HTTPException(status_code=503, detail="Service de sécurité temporairement indisponible") from None


def enforce_login_limit(identifier: str, store: RedisStore | None) -> None:
    _enforce_limit(identifier, store, password_change=False)


def enforce_password_change_limit(identifier: str, store: RedisStore | None) -> None:
    _enforce_limit(identifier, store, password_change=True)


def _user_response(db: Session, user: User) -> dict:
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "company_id": user.company_id,
        "company_name": company.name if company else None,
        "is_active": user.is_active,
        "avatar_url": user.avatar_url,
        "phone": user.phone,
        "created_at": user.created_at,
    }


def _login(identifier: str, password: str, db: Session, store: RedisStore | None) -> dict:
    enforce_login_limit(identifier, store)
    user = db.query(User).filter(User.email == identifier).first()
    if not user:
        # Do comparable bcrypt work even for an unknown identifier. This
        # reduces, but cannot completely eliminate, account timing differences.
        verify_password(password, _DUMMY_LOGIN_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")

    # Capture BOTH the password hash and the epoch before verification. If a
    # password change or logout races with this request, the conditional update
    # fails or the token retains the old epoch and is rejected on its next use.
    user_id, password_hash, previous_nonce = user.id, user.hashed_password, user.session_nonce
    verified = verify_password(password, password_hash if user.is_active else _DUMMY_LOGIN_HASH)
    if not user.is_active or not verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")
    if previous_nonce is not None and not is_valid_session_nonce(previous_nonce):
        raise HTTPException(status_code=503, detail="Compte temporairement indisponible")
    token_nonce = previous_nonce if previous_nonce is not None else new_session_nonce()
    result = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.hashed_password == password_hash,
            User.session_nonce == previous_nonce,
            User.is_active.is_(True),
        )
        .values(session_nonce=token_nonce, last_login=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Le compte a changé pendant la connexion. Réessayez.")
    db.commit()

    return {
        "access_token": create_access_token(subject=user_id, session_nonce=token_nonce),
        "token_type": "bearer",
        "user": _user_response(db, user),
    }


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db), store: RedisStore | None = Depends(get_redis_store)):
    return _login(form_data.username, form_data.password, db, store)


@router.post("/login-json", response_model=TokenResponse)
def login_json(payload: LoginRequest, db: Session = Depends(get_db), store: RedisStore | None = Depends(get_redis_store)):
    return _login(payload.email, payload.password, db, store)


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Les inscriptions publiques sont désactivées")
    if not is_acceptable_new_password(payload.password):
        raise HTTPException(status_code=400, detail="Mot de passe : au moins 16 caractères, au plus 72 octets, sans espaces aux extrémités")
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Un compte avec cet email existe déjà")

    company_name = payload.company_name or f"Entreprise de {payload.first_name}"
    company = Company(
        name=company_name,
        slug=company_name.lower().replace(" ", "-") + f"-{int(datetime.now(timezone.utc).timestamp())}",
    )
    db.add(company)
    db.flush()
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role="admin",
        company_id=company.id,
    )
    db.add(user)
    db.flush()
    # As with login, never reload a newer epoch after authenticating.
    user_id, token_nonce, company_id = user.id, user.session_nonce, company.id
    db.commit()
    ensure_default_stages(db, company_id)
    return {
        "access_token": create_access_token(subject=user_id, session_nonce=token_nonce),
        "token_type": "bearer",
        "user": _user_response(db, user),
    }


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    store: RedisStore | None = Depends(get_redis_store),
):
    enforce_password_change_limit(current_user.email, store)
    # Keep the snapshot attached to the authenticated request. A concurrent
    # logout, password change or account change must never be undone here.
    user_id, password_hash, old_nonce = current_user.id, current_user.hashed_password, current_user.session_nonce
    if not verify_password(payload.old_password, password_hash):
        # This is not an expired session; a 401 would log the browser out.
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if not is_acceptable_new_password(payload.new_password):
        raise HTTPException(status_code=400, detail="Mot de passe : au moins 16 caractères, au plus 72 octets, sans espaces aux extrémités")
    if verify_password(payload.new_password, password_hash):
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit être différent")

    new_hash, new_nonce = get_password_hash(payload.new_password), new_session_nonce()
    result = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.hashed_password == password_hash,
            User.session_nonce == old_nonce,
            User.is_active.is_(True),
        )
        .values(hashed_password=new_hash, session_nonce=new_nonce)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    db.commit()
    return {"message": "Mot de passe modifié. Toutes les sessions sont déconnectées."}


@router.post("/logout-all")
def logout_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(
        update(User)
        .where(
            User.id == current_user.id,
            User.session_nonce == current_user.session_nonce,
            User.is_active.is_(True),
        )
        .values(session_nonce=new_session_nonce())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    db.commit()
    return {"message": "Toutes les sessions sont déconnectées."}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_response(db, current_user)
