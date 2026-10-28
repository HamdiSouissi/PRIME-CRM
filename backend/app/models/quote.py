from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, Date
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta, date
from ..database import Base

class Quote(Base):
    __tablename__ = "quotes"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    number = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    status = Column(String(20), default="draft")  # draft, sent, accepted, refused, expired
    valid_until = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    terms = Column(Text, nullable=True)
    
    subtotal = Column(Float, default=0)
    discount_percent = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    total = Column(Float, default=0)
    currency = Column(String(10), default="TND")
    
    version = Column(Integer, default=1)
    parent_id = Column(Integer, ForeignKey("quotes.id"), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    sent_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    
    company = relationship("Company")
    client = relationship("Client", back_populates="quotes")
    opportunity = relationship("Opportunity")
    owner = relationship("User", foreign_keys=[owner_id])
    lines = relationship("QuoteLine", back_populates="quote", cascade="all, delete-orphan")
    parent = relationship("Quote", remote_side=[id])

class QuoteLine(Base):
    __tablename__ = "quote_lines"
    
    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Float, default=1)
    unit = Column(String(20), default="pièce")
    unit_price = Column(Float, default=0)
    discount_percent = Column(Float, default=0)
    tax_rate = Column(Float, default=19)
    line_total = Column(Float, default=0)
    order = Column(Integer, default=0)
    
    quote = relationship("Quote", back_populates="lines")
    product = relationship("Product")
