from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Enum, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    type = Column(String(20), default="prospect")  # prospect, client, partenaire
    status = Column(String(20), default="actif")  # actif, inactif, archivé
    category = Column(String(100), nullable=True)
    sector = Column(String(100), nullable=True)
    source = Column(String(100), nullable=True)
    tags = Column(Text, nullable=True)  # JSON string
    
    # Entreprise
    company_name = Column(String(255), nullable=False)
    legal_name = Column(String(255), nullable=True)
    tax_id = Column(String(100), nullable=True)
    
    # Contact principal
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(50), nullable=True)
    mobile = Column(String(50), nullable=True)
    position = Column(String(100), nullable=True)
    
    # Adresse
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    zip_code = Column(String(20), nullable=True)
    country = Column(String(100), default="Tunisie")
    website = Column(String(255), nullable=True)
    
    # Commercial
    notes = Column(Text, nullable=True)
    annual_revenue = Column(Float, nullable=True)
    employees_count = Column(Integer, nullable=True)
    
    is_archived = Column(Boolean, default=False)
    last_interaction_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company", back_populates="clients")
    owner = relationship("User", foreign_keys=[owner_id])
    contacts = relationship("Contact", back_populates="client", cascade="all, delete-orphan")
    opportunities = relationship("Opportunity", back_populates="client", cascade="all, delete-orphan")
    activities = relationship("Activity", back_populates="client", cascade="all, delete-orphan")
    quotes = relationship("Quote", back_populates="client")
