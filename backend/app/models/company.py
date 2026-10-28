from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True)
    logo_url = Column(String(512), nullable=True)
    primary_color = Column(String(20), default="#0ea5e9")
    secondary_color = Column(String(20), default="#0284c7")
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), default="Tunisie")
    tax_id = Column(String(100), nullable=True)  # Matricule fiscal
    currency = Column(String(10), default="TND")
    locale = Column(String(10), default="fr-TN")
    timezone = Column(String(50), default="Africa/Tunis")
    quote_prefix = Column(String(20), default="DEV")
    quote_counter = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="company", cascade="all, delete-orphan")
    opportunities = relationship("Opportunity", back_populates="company")
    products = relationship("Product", back_populates="company")
    stages = relationship("PipelineStage", back_populates="company")
