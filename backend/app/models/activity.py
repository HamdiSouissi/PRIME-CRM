from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Date, Time
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class Activity(Base):
    __tablename__ = "activities"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True, index=True)
    
    type = Column(String(50), nullable=False)  # task, call, meeting, email, note
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="todo")  # todo, in_progress, done, cancelled
    priority = Column(String(20), default="medium")  # low, medium, high, urgent
    
    due_date = Column(Date, nullable=True)
    due_time = Column(String(20), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    location = Column(String(255), nullable=True)
    
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    reminder_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company")
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", back_populates="activities")
    opportunity = relationship("Opportunity", back_populates="activities")
