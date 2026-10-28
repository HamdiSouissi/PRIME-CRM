from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from ..database import Base

class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    
    provider = Column(String(50), nullable=False)  # ollama, codecraftapi, openai_compat
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    
    # Ollama
    ollama_url = Column(String(255), nullable=True, default="http://host.docker.internal:11434")
    ollama_model = Column(String(100), nullable=True, default="llama3.2")
    
    # CodeCraftAPI / OpenAI compatible
    api_base_url = Column(String(255), nullable=True, default="https://www.codecraftapi.com/v1")
    api_key_encrypted = Column(Text, nullable=True)  # stored encrypted / masked
    model_id = Column(String(100), nullable=True, default="gpt-4o-mini")
    
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=1000)
    timeout_seconds = Column(Integer, default=30)
    
    # Feature mapping: which provider per feature
    feature_mapping = Column(Text, nullable=True)  # JSON: {"client_summary": "ollama", "email_draft": "codecraftapi"}
    
    last_test_at = Column(DateTime, nullable=True)
    last_test_status = Column(String(50), nullable=True)
    last_test_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    company = relationship("Company")
