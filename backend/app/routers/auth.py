from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, timezone

from ..database import get_db
from ..models.user import User
from ..models.company import Company
from ..models.stage import PipelineStage
from ..core.security import verify_password, get_password_hash, create_access_token, is_acceptable_new_password
from ..core.permissions import get_current_user
from ..config import settings
from ..schemas.auth import LoginRequest, TokenResponse, UserResponse, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

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
                is_lost=s.get("is_lost", False)
            )
            db.add(stage)
        db.commit()

@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Compte désactivé")
    
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    
    access_token = create_access_token(subject=user.id)
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
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
            "created_at": user.created_at
        }
    }

@router.post("/login-json", response_model=TokenResponse)
def login_json(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Compte désactivé")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    access_token = create_access_token(subject=user.id)
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
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
            "created_at": user.created_at
        }
    }

@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Les inscriptions publiques sont désactivées")
    if not is_acceptable_new_password(payload.password):
        raise HTTPException(status_code=400, detail="Mot de passe : au moins 16 caractères, au plus 72 octets, sans espaces aux extrémités")
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Un compte avec cet email existe déjà")
    
    # Create company for this user (multi-tenant isolation)
    company_name = payload.company_name or f"Entreprise de {payload.first_name}"
    company = Company(
        name=company_name,
        slug=company_name.lower().replace(" ", "-") + f"-{int(datetime.now(timezone.utc).timestamp())}"
    )
    db.add(company)
    db.flush()
    
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role="admin",
        company_id=company.id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    ensure_default_stages(db, company.id)
    
    access_token = create_access_token(subject=user.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "company_id": user.company_id,
            "company_name": company.name,
            "is_active": user.is_active,
            "avatar_url": user.avatar_url,
            "phone": user.phone,
            "created_at": user.created_at
        }
    }

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    return {
        "id": current_user.id,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "company_name": company.name if company else None,
        "is_active": current_user.is_active,
        "avatar_url": current_user.avatar_url,
        "phone": current_user.phone,
        "created_at": current_user.created_at
    }
