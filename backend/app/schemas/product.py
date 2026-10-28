from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProductCreate(BaseModel):
    name: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str = "pièce"
    price: float = 0
    cost: Optional[float] = None
    tax_rate: float = 19.0
    is_active: bool = True

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    tax_rate: Optional[float] = None
    is_active: Optional[bool] = None

class ProductResponse(BaseModel):
    id: int
    company_id: int
    name: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str
    price: float
    cost: Optional[float] = None
    tax_rate: float
    is_active: bool
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
