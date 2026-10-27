from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, Date
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class Opportunity(Base):
    __tablename__ = "opportunities"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=False)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Float, nullable=False, default=0)
    probability = Column(Integer, default=50)  # 0-100
    expected_close_date = Column(Date, nullable=True)
    source = Column(String(100), nullable=True)
    next_action = Column(Text, nullable=True)
    loss_reason = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    
    # Alert tracking
    last_activity_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_stale = Column(String(20), default="active")  # active, stale, blocked
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    
    company = relationship("Company", back_populates="opportunities")
    client = relationship("Client", back_populates="opportunities")
    owner = relationship("User", foreign_keys=[owner_id])
    stage = relationship("PipelineStage", back_populates="opportunities")
    activities = relationship("Activity", back_populates="opportunity", cascade="all, delete-orphan")
    
    @property
    def weighted_amount(self):
        return (self.amount or 0) * (self.probability or 0) / 100
