from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional, List
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..models.contact import Contact
from ..models.audit import AuditLog
from ..core.permissions import get_current_user
from ..schemas.client import ClientCreate, ClientUpdate, ClientResponse, PaginatedClients, MergeRequest
from datetime import datetime, timezone
import csv, io, json

router = APIRouter(prefix="/clients", tags=["clients"])

def to_response(client: Client, db: Session) -> dict:
    owner = db.query(User).filter(User.id == client.owner_id).first() if client.owner_id else None
    return {
        "id": client.id,
        "company_id": client.company_id,
        "owner_id": client.owner_id,
        "type": client.type,
        "status": client.status,
        "category": client.category,
        "sector": client.sector,
        "source": client.source,
        "tags": client.tags,
        "company_name": client.company_name,
        "legal_name": client.legal_name,
        "tax_id": client.tax_id,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "mobile": client.mobile,
        "position": client.position,
        "address": client.address,
        "city": client.city,
        "zip_code": client.zip_code,
        "country": client.country,
        "website": client.website,
        "notes": client.notes,
        "is_archived": client.is_archived,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
        "owner_name": f"{owner.first_name} {owner.last_name}" if owner else None
    }

@router.get("", response_model=PaginatedClients)
def list_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    sector: Optional[str] = None,
    source: Optional[str] = None,
    owner_id: Optional[int] = None,
    is_archived: Optional[bool] = None,
    sort_by: str = Query("created_at", regex="^(created_at|company_name|updated_at|city)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
):
    query = db.query(Client).filter(Client.company_id == current_user.company_id)
    
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Client.company_name.ilike(like),
            Client.email.ilike(like),
            Client.phone.ilike(like),
            Client.city.ilike(like),
            Client.first_name.ilike(like),
            Client.last_name.ilike(like),
        ))
    if type:
        query = query.filter(Client.type == type)
    if status:
        query = query.filter(Client.status == status)
    if sector:
        query = query.filter(Client.sector == sector)
    if source:
        query = query.filter(Client.source == source)
    if owner_id:
        query = query.filter(Client.owner_id == owner_id)
    if is_archived is not None:
        query = query.filter(Client.is_archived == is_archived)
    
    total = query.count()
    order_col = getattr(Client, sort_by)
    if sort_order == "desc":
        order_col = order_col.desc()
    items = query.order_by(order_col).offset((page-1)*page_size).limit(page_size).all()
    
    return {
        "items": [to_response(c, db) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size -1)//page_size if total else 0
    }

@router.post("", response_model=ClientResponse)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), request: Request = None):
    data = payload.model_dump()
    data.pop("owner_id", None)
    client = Client(
        company_id=current_user.company_id,
        owner_id=payload.owner_id or current_user.id,
        **data
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    
    # audit
    try:
        audit = AuditLog(company_id=current_user.company_id, user_id=current_user.id, action="create", entity_type="client", entity_id=client.id, details=json.dumps({"company_name": client.company_name}))
        db.add(audit); db.commit()
    except: pass
    
    return to_response(client, db)

@router.get("/duplicates")
def find_duplicates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Détection simple de doublons : même email ou même téléphone ou nom similaire"""
    clients = db.query(Client).filter(Client.company_id == current_user.company_id, Client.is_archived == False).all()
    seen_email = {}
    seen_phone = {}
    duplicates = []
    
    for c in clients:
        if c.email:
            key = c.email.lower().strip()
            if key in seen_email:
                duplicates.append({"group": [to_response(seen_email[key], db), to_response(c, db)], "reason": f"Email identique: {c.email}"})
            else:
                seen_email[key] = c
        if c.phone:
            key = c.phone.strip().replace(" ", "").replace("-", "")
            if key in seen_phone and key:
                # Avoid duplicate reporting same pair
                existing = seen_phone[key]
                if existing.email != c.email:  # different already captured?
                    duplicates.append({"group": [to_response(existing, db), to_response(c, db)], "reason": f"Téléphone identique: {c.phone}"})
            else:
                seen_phone[key] = c
    
    # Company name similarity (exact lower)
    seen_name = {}
    for c in clients:
        key = c.company_name.lower().strip()
        if key in seen_name and key not in [d["reason"] for d in []]:
            if seen_name[key].id != c.id:
                # check not already reported via email/phone
                already = any(c.id in [x["id"] for x in d["group"]] and seen_name[key].id in [x["id"] for x in d["group"]] for d in duplicates)
                if not already:
                    duplicates.append({"group": [to_response(seen_name[key], db), to_response(c, db)], "reason": f"Nom d'entreprise identique: {c.company_name}"})
        else:
            seen_name[key] = c
    
    return duplicates

@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    return to_response(client, db)

@router.get("/{client_id}/full")
def get_client_full(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from ..models.opportunity import Opportunity
    from ..models.activity import Activity
    from ..models.quote import Quote
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    contacts = db.query(Contact).filter(Contact.client_id == client_id).all()
    opportunities = db.query(Opportunity).filter(Opportunity.client_id == client_id).all()
    activities = db.query(Activity).filter(Activity.client_id == client_id).order_by(Activity.created_at.desc()).limit(50).all()
    quotes = db.query(Quote).filter(Quote.client_id == client_id).all()
    
    # enrich activities with owner names
    def act_to_dict(a):
        owner = db.query(User).filter(User.id == a.owner_id).first() if a.owner_id else None
        return {
            "id": a.id, "type": a.type, "title": a.title, "description": a.description, "status": a.status,
            "priority": a.priority, "due_date": a.due_date, "is_completed": a.is_completed, "created_at": a.created_at,
            "owner_name": f"{owner.first_name} {owner.last_name}" if owner else None
        }
    
    return {
        "client": to_response(client, db),
        "contacts": [{"id": c.id, "first_name": c.first_name, "last_name": c.last_name, "email": c.email, "phone": c.phone, "position": c.position, "is_primary": c.is_primary} for c in contacts],
        "opportunities": [{"id": o.id, "title": o.title, "amount": o.amount, "stage_id": o.stage_id, "probability": o.probability, "created_at": o.created_at} for o in opportunities],
        "activities": [act_to_dict(a) for a in activities],
        "quotes": [{"id": q.id, "number": q.number, "title": q.title, "status": q.status, "total": q.total, "created_at": q.created_at} for q in quotes],
        "history": [act_to_dict(a) for a in activities]  # same for now, could include audit logs
    }

@router.put("/{client_id}", response_model=ClientResponse)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    client.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(client)
    return to_response(client, db)

@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    # soft delete -> archive, but allow hard delete if query param?
    client.is_archived = True
    db.commit()
    return {"message": "Client archivé"}

@router.post("/{client_id}/archive")
def archive_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    client.is_archived = not client.is_archived
    db.commit()
    return {"is_archived": client.is_archived}

@router.post("/merge")
def merge_clients(payload: MergeRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target = db.query(Client).filter(Client.id == payload.target_id, Client.company_id == current_user.company_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Client cible non trouvé")
    for sid in payload.source_ids:
        if sid == payload.target_id:
            continue
        source = db.query(Client).filter(Client.id == sid, Client.company_id == current_user.company_id).first()
        if not source:
            continue
        # move contacts, opportunities, activities, quotes
        from ..models.opportunity import Opportunity
        from ..models.activity import Activity
        from ..models.quote import Quote
        db.query(Contact).filter(Contact.client_id == source.id).update({Contact.client_id: target.id})
        db.query(Opportunity).filter(Opportunity.client_id == source.id).update({Opportunity.client_id: target.id})
        db.query(Activity).filter(Activity.client_id == source.id).update({Activity.client_id: target.id})
        db.query(Quote).filter(Quote.client_id == source.id).update({Quote.client_id: target.id})
        # merge notes
        if source.notes:
            target.notes = (target.notes or "") + f"\n\n--- Fusion depuis {source.company_name} ---\n" + source.notes
        # keep best email/phone if target missing
        if not target.email and source.email:
            target.email = source.email
        if not target.phone and source.phone:
            target.phone = source.phone
        db.delete(source)
    db.commit()
    # audit
    try:
        audit = AuditLog(company_id=current_user.company_id, user_id=current_user.id, action="merge", entity_type="client", entity_id=target.id, details=json.dumps({"merged_ids": payload.source_ids}))
        db.add(audit); db.commit()
    except: pass
    return to_response(target, db)

# Contacts sub-resource
@router.get("/{client_id}/contacts")
def list_contacts(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    contacts = db.query(Contact).filter(Contact.client_id == client_id).all()
    return [{"id": c.id, "client_id": c.client_id, "first_name": c.first_name, "last_name": c.last_name, "email": c.email, "phone": c.phone, "mobile": c.mobile, "position": c.position, "department": c.department, "is_primary": c.is_primary, "notes": c.notes, "created_at": c.created_at} for c in contacts]

@router.post("/{client_id}/contacts")
def create_contact(client_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    contact = Contact(client_id=client_id, **{k: v for k, v in payload.items() if k in ["first_name","last_name","email","phone","mobile","position","department","is_primary","notes"]})
    db.add(contact); db.commit(); db.refresh(contact)
    return {"id": contact.id, "first_name": contact.first_name, "last_name": contact.last_name, "email": contact.email, "phone": contact.phone, "position": contact.position, "is_primary": contact.is_primary}

@router.put("/{client_id}/contacts/{contact_id}")
def update_contact(client_id: int, contact_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.client_id == client_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact non trouvé")
    for k, v in payload.items():
        if hasattr(contact, k):
            setattr(contact, k, v)
    db.commit(); db.refresh(contact)
    return {"id": contact.id, "first_name": contact.first_name, "last_name": contact.last_name, "email": contact.email, "phone": contact.phone, "position": contact.position, "is_primary": contact.is_primary}

@router.delete("/{client_id}/contacts/{contact_id}")
def delete_contact(client_id: int, contact_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.client_id == client_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact non trouvé")
    db.delete(contact); db.commit()
    return {"message": "Contact supprimé"}
