from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models.user import User
from ..core.security import get_password_hash, is_acceptable_new_password
from ..core.permissions import get_current_user, require_admin
from ..schemas.auth import UserResponse
from pydantic import BaseModel, EmailStr
from typing import Optional

router = APIRouter(prefix="/users", tags=["users"])

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    role: str = "commercial"
    phone: Optional[str] = None

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None

@router.get("", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    users = db.query(User).filter(User.company_id == current_user.company_id).all()
    from ..models.company import Company
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    result = []
    for u in users:
        result.append({
            "id": u.id, "email": u.email, "first_name": u.first_name, "last_name": u.last_name,
            "role": u.role, "company_id": u.company_id, "company_name": company.name if company else None,
            "is_active": u.is_active, "avatar_url": u.avatar_url, "phone": u.phone, "created_at": u.created_at
        })
    return result

@router.post("", response_model=UserResponse)
def create_user(payload: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if not is_acceptable_new_password(payload.password):
        raise HTTPException(status_code=400, detail="Mot de passe : au moins 16 caractères, au plus 72 octets, sans espaces aux extrémités")
    if payload.role not in {"admin", "manager", "commercial", "viewer"}:
        raise HTTPException(status_code=400, detail="Rôle invalide")
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        phone=payload.phone,
        company_id=current_user.company_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    from ..models.company import Company
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "company_id": user.company_id, "company_name": company.name if company else None,
        "is_active": user.is_active, "avatar_url": user.avatar_url, "phone": user.phone, "created_at": user.created_at
    }

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    from ..models.company import Company
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "company_id": user.company_id, "company_name": company.name if company else None,
        "is_active": user.is_active, "avatar_url": user.avatar_url, "phone": user.phone, "created_at": user.created_at
    }

@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    from ..models.company import Company
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {
        "id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "company_id": user.company_id, "company_name": company.name if company else None,
        "is_active": user.is_active, "avatar_url": user.avatar_url, "phone": user.phone, "created_at": user.created_at
    }

@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer votre propre compte")
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    db.delete(user)
    db.commit()
    return {"message": "Utilisateur supprimé"}
