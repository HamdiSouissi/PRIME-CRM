from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    color = Column(String(20), default="#0ea5e9")
    order = Column(Integer, default=0)
    is_won = Column(Boolean, default=False)
    is_lost = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company", back_populates="stages")
    opportunities = relationship("Opportunity", back_populates="stage")
