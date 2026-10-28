from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"

class UserResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    company_id: int
    company_name: Optional[str] = None
    is_active: bool
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    company_name: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
