from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime

class AIProviderCreate(BaseModel):
    provider: str  # ollama, codecraftapi
    name: str
    is_active: bool = False
    is_default: bool = False
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1000
    timeout_seconds: int = 30
    feature_mapping: Optional[Dict[str, str]] = None

class AIProviderUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_seconds: Optional[int] = None
    feature_mapping: Optional[Dict[str, str]] = None

class AIProviderResponse(BaseModel):
    id: int
    company_id: int
    provider: str
    name: str
    is_active: bool
    is_default: bool
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key_masked: Optional[str] = None
    model_id: Optional[str] = None
    temperature: float
    max_tokens: int
    timeout_seconds: int
    feature_mapping: Optional[Dict[str, str]] = None
    last_test_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    last_test_message: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class AITestRequest(BaseModel):
    provider_id: Optional[int] = None
    provider: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None

class AITestResponse(BaseModel):
    success: bool
    message: str
    models: Optional[List[str]] = None
    latency_ms: Optional[int] = None

class AIModelsResponse(BaseModel):
    models: List[str]

class AIGenerateRequest(BaseModel):
    prompt: str
    feature: Optional[str] = None  # client_summary, email_draft, etc
    provider_id: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    context: Optional[Dict[str, Any]] = None

class AIGenerateResponse(BaseModel):
    content: str
    provider: str
    model: str
    is_verified: bool = False  # distinguish verified data vs suggestion
    tokens_used: Optional[int] = None

class AISummaryRequest(BaseModel):
    client_id: int

class AIExtractRequest(BaseModel):
    text: str
    schema_hint: Optional[str] = None
