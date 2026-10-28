from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone, date, timedelta
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..models.company import Company
from ..models.quote import Quote, QuoteLine
from ..models.product import Product
from ..core.permissions import get_current_user
from ..schemas.quote import QuoteCreate, QuoteUpdate, QuoteResponse
from ..services.pdf_service import generate_quote_pdf
import io

router = APIRouter(prefix="/quotes", tags=["quotes"])

def compute_totals(quote: Quote, db: Session):
    subtotal = 0
    tax_amount = 0
    for line in quote.lines:
        line_total_before_tax = line.quantity * line.unit_price * (1 - (line.discount_percent or 0)/100)
        line_tax = line_total_before_tax * (line.tax_rate or 0)/100
        line.line_total = round(line_total_before_tax + line_tax, 2)
        subtotal += line_total_before_tax
        tax_amount += line_tax
    discount_amount = subtotal * (quote.discount_percent or 0)/100
    subtotal_after_discount = subtotal - discount_amount
    # tax should be recalculated after discount proportionally? Simple: tax on subtotal_after_discount
    # Already line tax includes discount, so recalc tax proportionally to discount
    if quote.discount_percent:
        tax_amount = tax_amount * (1 - quote.discount_percent/100)
    quote.subtotal = round(subtotal, 2)
    quote.discount_amount = round(discount_amount, 2)
    quote.tax_amount = round(tax_amount, 2)
    quote.total = round(subtotal_after_discount + tax_amount, 2)

def to_response(quote: Quote, db: Session):
    client = db.query(Client).filter(Client.id == quote.client_id).first()
    owner = db.query(User).filter(User.id == quote.owner_id).first() if quote.owner_id else None
    lines = db.query(QuoteLine).filter(QuoteLine.quote_id == quote.id).order_by(QuoteLine.order).all()
    return {
        "id": quote.id,
        "company_id": quote.company_id,
        "client_id": quote.client_id,
        "opportunity_id": quote.opportunity_id,
        "owner_id": quote.owner_id,
        "number": quote.number,
        "title": quote.title,
        "status": quote.status,
        "valid_until": quote.valid_until,
        "notes": quote.notes,
        "terms": quote.terms,
        "subtotal": quote.subtotal or 0,
        "discount_percent": quote.discount_percent or 0,
        "discount_amount": quote.discount_amount or 0,
        "tax_amount": quote.tax_amount or 0,
        "total": quote.total or 0,
        "currency": quote.currency,
        "version": quote.version,
        "created_at": quote.created_at,
        "updated_at": quote.updated_at,
        "lines": [{"id": l.id, "quote_id": l.quote_id, "product_id": l.product_id, "name": l.name, "description": l.description, "quantity": l.quantity, "unit": l.unit, "unit_price": l.unit_price, "discount_percent": l.discount_percent, "tax_rate": l.tax_rate, "line_total": l.line_total} for l in lines],
        "client_name": client.company_name if client else None,
        "owner_name": f"{owner.first_name} {owner.last_name}" if owner else None
    }

@router.get("", response_model=List[QuoteResponse])
def list_quotes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), status: Optional[str] = None, client_id: Optional[int] = None):
    query = db.query(Quote).filter(Quote.company_id == current_user.company_id)
    if status:
        query = query.filter(Quote.status == status)
    if client_id:
        query = query.filter(Quote.client_id == client_id)
    quotes = query.order_by(Quote.created_at.desc()).all()
    return [to_response(q, db) for q in quotes]

@router.post("", response_model=QuoteResponse)
def create_quote(payload: QuoteCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == payload.client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    number = f"{company.quote_prefix or 'DEV'}-{company.quote_counter:04d}-{datetime.now(timezone.utc).year}" if company else f"DEV-{int(datetime.now(timezone.utc).timestamp())}"
    if company:
        company.quote_counter += 1
    
    quote = Quote(
        company_id=current_user.company_id,
        client_id=payload.client_id,
        opportunity_id=payload.opportunity_id,
        owner_id=current_user.id,
        number=number,
        title=payload.title,
        valid_until=payload.valid_until or (date.today() + timedelta(days=30)),
        notes=payload.notes,
        terms=payload.terms,
        discount_percent=payload.discount_percent,
        currency=payload.currency,
    )
    db.add(quote)
    db.flush()  # get id
    
    for idx, line_data in enumerate(payload.lines):
        line = QuoteLine(
            quote_id=quote.id,
            order=idx,
            **line_data.model_dump()
        )
        db.add(line)
    db.commit()
    db.refresh(quote)
    # compute totals
    quote = db.query(Quote).filter(Quote.id == quote.id).first()
    compute_totals(quote, db)
    db.commit(); db.refresh(quote)
    return to_response(quote, db)

@router.get("/{quote_id}", response_model=QuoteResponse)
def get_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.company_id == current_user.company_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    return to_response(quote, db)

@router.put("/{quote_id}", response_model=QuoteResponse)
def update_quote(quote_id: int, payload: QuoteUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.company_id == current_user.company_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    
    # handle status transitions
    if payload.status:
        # validate transitions
        if payload.status in ["sent", "accepted", "refused", "expired"]:
            if payload.status == "sent":
                quote.sent_at = datetime.now(timezone.utc)
            if payload.status == "accepted":
                quote.accepted_at = datetime.now(timezone.utc)
    for k, v in payload.model_dump(exclude_unset=True, exclude={"lines"}).items():
        setattr(quote, k, v)
    
    if payload.lines is not None:
        # replace lines
        db.query(QuoteLine).filter(QuoteLine.quote_id == quote.id).delete()
        for idx, line_data in enumerate(payload.lines):
            line = QuoteLine(quote_id=quote.id, order=idx, **line_data.model_dump())
            db.add(line)
        db.flush()
    
    compute_totals(quote, db)
    # version handling: if status was sent and now editing, increment version? Keep simple.
    if quote.status == "sent" and payload.lines is not None:
        quote.version += 1
    
    db.commit(); db.refresh(quote)
    return to_response(quote, db)

@router.post("/{quote_id}/duplicate", response_model=QuoteResponse)
def duplicate_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    orig = db.query(Quote).filter(Quote.id == quote_id, Quote.company_id == current_user.company_id).first()
    if not orig:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    number = f"{company.quote_prefix or 'DEV'}-{company.quote_counter:04d}-{datetime.now(timezone.utc).year}" if company else f"DEV-{int(datetime.now(timezone.utc).timestamp())}"
    if company:
        company.quote_counter += 1
    new_quote = Quote(
        company_id=orig.company_id,
        client_id=orig.client_id,
        opportunity_id=orig.opportunity_id,
        owner_id=current_user.id,
        number=number,
        title=orig.title + " (copie)",
        status="draft",
        valid_until=date.today() + timedelta(days=30),
        notes=orig.notes,
        terms=orig.terms,
        discount_percent=orig.discount_percent,
        currency=orig.currency,
        parent_id=orig.id,
        version=1
    )
    db.add(new_quote); db.flush()
    lines = db.query(QuoteLine).filter(QuoteLine.quote_id == orig.id).all()
    for l in lines:
        nl = QuoteLine(quote_id=new_quote.id, product_id=l.product_id, name=l.name, description=l.description, quantity=l.quantity, unit=l.unit, unit_price=l.unit_price, discount_percent=l.discount_percent, tax_rate=l.tax_rate, order=l.order)
        db.add(nl)
    db.commit(); db.refresh(new_quote)
    compute_totals(new_quote, db); db.commit(); db.refresh(new_quote)
    return to_response(new_quote, db)

@router.get("/{quote_id}/pdf")
def get_quote_pdf(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.company_id == current_user.company_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    company = db.query(Company).filter(Company.id == quote.company_id).first()
    client = db.query(Client).filter(Client.id == quote.client_id).first()
    lines = db.query(QuoteLine).filter(QuoteLine.quote_id == quote.id).all()
    
    pdf_bytes = generate_quote_pdf(quote, company, client, lines)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={quote.number}.pdf"})

@router.delete("/{quote_id}")
def delete_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.company_id == current_user.company_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    db.delete(quote); db.commit()
    return {"message": "Devis supprimé"}
