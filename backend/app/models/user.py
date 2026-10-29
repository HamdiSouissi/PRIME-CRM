from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base
from ..core.security import new_session_nonce

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    # NULL is allowed only for pre-migration accounts; their first login
    # atomically initializes a random value and invalidates legacy tokens.
    session_nonce = Column(String(43), nullable=True, default=new_session_nonce)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(50), default="commercial")  # admin, manager, commercial, viewer
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    avatar_url = Column(String(512), nullable=True)
    phone = Column(String(50), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company", back_populates="users")
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
