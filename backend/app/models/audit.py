from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    action = Column(String(100), nullable=False)  # create, update, delete, login, export, etc
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)  # JSON
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    user = relationship("User")
    company = relationship("Company")
