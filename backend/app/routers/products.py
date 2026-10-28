from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from ..database import get_db
from ..models.user import User
from ..models.product import Product
from ..core.permissions import get_current_user
from ..schemas.product import ProductCreate, ProductUpdate, ProductResponse

router = APIRouter(prefix="/products", tags=["products"])

@router.get("", response_model=List[ProductResponse])
def list_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), search: Optional[str] = None, category: Optional[str] = None, is_active: Optional[bool] = None):
    query = db.query(Product).filter(Product.company_id == current_user.company_id)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.description.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if is_active is not None:
        query = query.filter(Product.is_active == is_active)
    products = query.order_by(Product.name).all()
    return [{"id": p.id, "company_id": p.company_id, "name": p.name, "sku": p.sku, "description": p.description, "category": p.category, "unit": p.unit, "price": p.price, "cost": p.cost, "tax_rate": p.tax_rate, "is_active": p.is_active, "created_at": p.created_at} for p in products]

@router.post("", response_model=ProductResponse)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    product = Product(company_id=current_user.company_id, **payload.model_dump())
    db.add(product); db.commit(); db.refresh(product)
    return {"id": product.id, "company_id": product.company_id, "name": product.name, "sku": product.sku, "description": product.description, "category": product.category, "unit": product.unit, "price": product.price, "cost": product.cost, "tax_rate": product.tax_rate, "is_active": product.is_active, "created_at": product.created_at}

@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Product).filter(Product.id == product_id, Product.company_id == current_user.company_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    return {"id": p.id, "company_id": p.company_id, "name": p.name, "sku": p.sku, "description": p.description, "category": p.category, "unit": p.unit, "price": p.price, "cost": p.cost, "tax_rate": p.tax_rate, "is_active": p.is_active, "created_at": p.created_at}

@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Product).filter(Product.id == product_id, Product.company_id == current_user.company_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return {"id": p.id, "company_id": p.company_id, "name": p.name, "sku": p.sku, "description": p.description, "category": p.category, "unit": p.unit, "price": p.price, "cost": p.cost, "tax_rate": p.tax_rate, "is_active": p.is_active, "created_at": p.created_at}

@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Product).filter(Product.id == product_id, Product.company_id == current_user.company_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    db.delete(p); db.commit()
    return {"message": "Produit supprimé"}
