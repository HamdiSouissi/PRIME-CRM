from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class ClientCreate(BaseModel):
    type: str = "prospect"
    status: str = "actif"
    category: Optional[str] = None
    sector: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[str] = None
    company_name: str
    legal_name: Optional[str] = None
    tax_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    position: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = "Tunisie"
    website: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[int] = None

class ClientUpdate(BaseModel):
    type: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    sector: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[str] = None
    company_name: Optional[str] = None
    legal_name: Optional[str] = None
    tax_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    position: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[int] = None
    is_archived: Optional[bool] = None

class ClientResponse(BaseModel):
    id: int
    company_id: int
    owner_id: Optional[int] = None
    type: str
    status: str
    category: Optional[str] = None
    sector: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[str] = None
    company_name: str
    legal_name: Optional[str] = None
    tax_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    position: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_archived: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    owner_name: Optional[str] = None
    
    class Config:
        from_attributes = True

class PaginatedClients(BaseModel):
    items: List[ClientResponse]
    total: int
    page: int
    page_size: int
    pages: int

class MergeRequest(BaseModel):
    source_ids: List[int]
    target_id: int

class DuplicateResponse(BaseModel):
    group: List[ClientResponse]
    reason: str
