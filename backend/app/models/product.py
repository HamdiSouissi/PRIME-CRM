from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    unit = Column(String(20), default="pièce")
    price = Column(Float, nullable=False, default=0)
    cost = Column(Float, nullable=True)
    tax_rate = Column(Float, default=19.0)  # Tunisie TVA 19%
    is_active = Column(Boolean, default=True)
    image_url = Column(String(512), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company", back_populates="products")
