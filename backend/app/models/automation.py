from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class AutomationRule(Base):
    __tablename__ = "automation_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(String(100), nullable=False)  # quote_no_response, opportunity_stage_change, client_inactive, before_meeting, opportunity_won
    trigger_config = Column(Text, nullable=True)  # JSON
    action_type = Column(String(100), nullable=False)  # create_task, send_notification, create_alert
    action_config = Column(Text, nullable=True)  # JSON
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    run_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company")
    executions = relationship("AutomationExecution", back_populates="rule", cascade="all, delete-orphan")

class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("automation_rules.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    trigger_data = Column(Text, nullable=True)  # JSON
    result = Column(Text, nullable=True)
    status = Column(String(20), default="success")  # success, failed, skipped
    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    rule = relationship("AutomationRule", back_populates="executions")
