from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

class QuoteLineCreate(BaseModel):
    product_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    quantity: float = 1
    unit: str = "pièce"
    unit_price: float = 0
    discount_percent: float = 0
    tax_rate: float = 19.0

class QuoteLineUpdate(BaseModel):
    product_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = None
    tax_rate: Optional[float] = None

class QuoteLineResponse(BaseModel):
    id: int
    quote_id: int
    product_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    quantity: float
    unit: str
    unit_price: float
    discount_percent: float
    tax_rate: float
    line_total: float
    
    class Config:
        from_attributes = True

class QuoteCreate(BaseModel):
    client_id: int
    opportunity_id: Optional[int] = None
    title: str
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    discount_percent: float = 0
    currency: str = "TND"
    lines: List[QuoteLineCreate] = []

class QuoteUpdate(BaseModel):
    client_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    title: Optional[str] = None
    status: Optional[str] = None
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    discount_percent: Optional[float] = None
    currency: Optional[str] = None
    lines: Optional[List[QuoteLineCreate]] = None

class QuoteResponse(BaseModel):
    id: int
    company_id: int
    client_id: int
    opportunity_id: Optional[int] = None
    owner_id: Optional[int] = None
    number: str
    title: str
    status: str
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    subtotal: float
    discount_percent: float
    discount_amount: float
    tax_amount: float
    total: float
    currency: str
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lines: List[QuoteLineResponse] = []
    client_name: Optional[str] = None
    owner_name: Optional[str] = None
    
    class Config:
        from_attributes = True
