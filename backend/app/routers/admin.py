from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
import json, io, datetime, os
from fastapi.responses import StreamingResponse
from ..database import get_db, engine
from ..models.user import User
from ..models.company import Company
from ..models.audit import AuditLog
from ..models.automation import AutomationRule, AutomationExecution
from ..models.client import Client
from ..core.permissions import get_current_user, require_admin
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin"])

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_id: Optional[str] = None
    currency: Optional[str] = None
    locale: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    quote_prefix: Optional[str] = None
    logo_url: Optional[str] = None

class AutomationRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: str
    trigger_config: Optional[dict] = None
    action_type: str
    action_config: Optional[dict] = None
    is_active: bool = True

class AutomationRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None
    action_type: Optional[str] = None
    action_config: Optional[dict] = None
    is_active: Optional[bool] = None

@router.get("/company")
def get_company(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    return {
        "id": company.id, "name": company.name, "slug": company.slug, "logo_url": company.logo_url,
        "primary_color": company.primary_color, "secondary_color": company.secondary_color,
        "email": company.email, "phone": company.phone, "address": company.address, "city": company.city, "country": company.country,
        "tax_id": company.tax_id, "currency": company.currency, "locale": company.locale, "timezone": company.timezone,
        "quote_prefix": company.quote_prefix, "quote_counter": company.quote_counter
    }

@router.put("/company")
def update_company(payload: CompanyUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    db.commit(); db.refresh(company)
    return {"message": "Entreprise mise à jour", "company": {"id": company.id, "name": company.name}}

@router.get("/audit-logs")
def list_audit_logs(db: Session = Depends(get_db), current_user: User = Depends(require_admin), limit: int = 100, offset: int = 0):
    logs = db.query(AuditLog).filter(AuditLog.company_id == current_user.company_id).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    total = db.query(AuditLog).filter(AuditLog.company_id == current_user.company_id).count()
    return {
        "items": [{"id": l.id, "action": l.action, "entity_type": l.entity_type, "entity_id": l.entity_id, "details": l.details, "user_id": l.user_id, "created_at": l.created_at} for l in logs],
        "total": total
    }

@router.get("/automation/rules")
def list_automation_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rules = db.query(AutomationRule).filter(AutomationRule.company_id == current_user.company_id).all()
    return [{"id": r.id, "name": r.name, "description": r.description, "trigger_type": r.trigger_type, "trigger_config": json.loads(r.trigger_config) if r.trigger_config else None, "action_type": r.action_type, "action_config": json.loads(r.action_config) if r.action_config else None, "is_active": r.is_active, "last_run_at": r.last_run_at, "run_count": r.run_count, "created_at": r.created_at} for r in rules]

@router.post("/automation/rules")
def create_automation_rule(payload: AutomationRuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rule = AutomationRule(
        company_id=current_user.company_id,
        name=payload.name,
        description=payload.description,
        trigger_type=payload.trigger_type,
        trigger_config=json.dumps(payload.trigger_config) if payload.trigger_config else None,
        action_type=payload.action_type,
        action_config=json.dumps(payload.action_config) if payload.action_config else None,
        is_active=payload.is_active
    )
    db.add(rule); db.commit(); db.refresh(rule)
    return {"id": rule.id, "name": rule.name}

@router.put("/automation/rules/{rule_id}")
def update_automation_rule(rule_id: int, payload: AutomationRuleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rule = db.query(AutomationRule).filter(AutomationRule.id==rule_id, AutomationRule.company_id==current_user.company_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Règle non trouvée")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k in ["trigger_config", "action_config"] and v is not None:
            setattr(rule, k, json.dumps(v))
        else:
            setattr(rule, k, v)
    db.commit(); db.refresh(rule)
    return {"message": "Règle mise à jour"}

@router.delete("/automation/rules/{rule_id}")
def delete_automation_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rule = db.query(AutomationRule).filter(AutomationRule.id==rule_id, AutomationRule.company_id==current_user.company_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Règle non trouvée")
    db.delete(rule); db.commit()
    return {"message": "Règle supprimée"}

@router.get("/automation/executions")
def list_executions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), limit: int = 50):
    exes = db.query(AutomationExecution).filter(AutomationExecution.company_id==current_user.company_id).order_by(AutomationExecution.executed_at.desc()).limit(limit).all()
    return [{"id": e.id, "rule_id": e.rule_id, "status": e.status, "result": e.result, "executed_at": e.executed_at} for e in exes]

@router.post("/backup")
def create_backup(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Export JSON de toutes les données de l'entreprise"""
    from ..models.client import Client
    from ..models.opportunity import Opportunity
    from ..models.activity import Activity
    from ..models.product import Product
    from ..models.quote import Quote
    from ..models.stage import PipelineStage
    
    company = db.query(Company).filter(Company.id==current_user.company_id).first()
    data = {
        "company": {"name": company.name, "email": company.email, "currency": company.currency},
        "clients": [{"company_name": c.company_name, "email": c.email, "phone": c.phone, "city": c.city} for c in db.query(Client).filter(Client.company_id==current_user.company_id).all()],
        "opportunities": [{"title": o.title, "amount": o.amount, "probability": o.probability} for o in db.query(Opportunity).filter(Opportunity.company_id==current_user.company_id).all()],
        "products": [{"name": p.name, "price": p.price} for p in db.query(Product).filter(Product.company_id==current_user.company_id).all()],
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "company_id": current_user.company_id
    }
    json_str = json.dumps(data, indent=2, default=str)
    return StreamingResponse(io.StringIO(json_str), media_type="application/json", headers={"Content-Disposition": f"attachment; filename=backup-{company.slug}-{datetime.date.today()}.json"})

@router.get("/stats")
def admin_stats(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    from ..models.client import Client
    from ..models.opportunity import Opportunity
    from ..models.activity import Activity
    return {
        "users": db.query(User).filter(User.company_id==current_user.company_id).count(),
        "clients": db.query(Client).filter(Client.company_id==current_user.company_id).count(),
        "opportunities": db.query(Opportunity).filter(Opportunity.company_id==current_user.company_id).count(),
        "activities": db.query(Activity).filter(Activity.company_id==current_user.company_id).count(),
        "audit_logs": db.query(AuditLog).filter(AuditLog.company_id==current_user.company_id).count(),
    }

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {
        "status": "ok",
        "database": db_status,
        "version": "1.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
