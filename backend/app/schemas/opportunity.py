from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

class OpportunityCreate(BaseModel):
    client_id: int
    stage_id: int
    owner_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    amount: float = 0
    probability: int = 50
    expected_close_date: Optional[date] = None
    source: Optional[str] = None
    next_action: Optional[str] = None
    tags: Optional[str] = None

class OpportunityUpdate(BaseModel):
    client_id: Optional[int] = None
    stage_id: Optional[int] = None
    owner_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    source: Optional[str] = None
    next_action: Optional[str] = None
    loss_reason: Optional[str] = None
    tags: Optional[str] = None

class OpportunityResponse(BaseModel):
    id: int
    company_id: int
    client_id: int
    owner_id: Optional[int] = None
    stage_id: int
    title: str
    description: Optional[str] = None
    amount: float
    probability: int
    expected_close_date: Optional[date] = None
    source: Optional[str] = None
    next_action: Optional[str] = None
    loss_reason: Optional[str] = None
    tags: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    weighted_amount: Optional[float] = None
    client_name: Optional[str] = None
    owner_name: Optional[str] = None
    stage_name: Optional[str] = None
    stage_color: Optional[str] = None
    
    class Config:
        from_attributes = True

class StageCreate(BaseModel):
    name: str
    color: str = "#0ea5e9"
    order: int = 0
    is_won: bool = False
    is_lost: bool = False

class StageUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None
    is_won: Optional[bool] = None
    is_lost: Optional[bool] = None

class StageResponse(BaseModel):
    id: int
    company_id: int
    name: str
    color: str
    order: int
    is_won: bool
    is_lost: bool
    opportunities_count: int = 0
    
    class Config:
        from_attributes = True

class PipelineResponse(BaseModel):
    stages: List[StageResponse]
    opportunities: List[OpportunityResponse]
    total_value: float = 0
    weighted_value: float = 0

class MoveOpportunityRequest(BaseModel):
    stage_id: int
    loss_reason: Optional[str] = None
