from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

class ActivityCreate(BaseModel):
    type: str  # task, call, meeting, email, note
    title: str
    description: Optional[str] = None
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    client_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    owner_id: Optional[int] = None
    reminder_at: Optional[datetime] = None

class ActivityUpdate(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    client_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    owner_id: Optional[int] = None
    is_completed: Optional[bool] = None

class ActivityResponse(BaseModel):
    id: int
    company_id: int
    owner_id: Optional[int] = None
    client_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    type: str
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    is_completed: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    client_name: Optional[str] = None
    owner_name: Optional[str] = None
    
    class Config:
        from_attributes = True
