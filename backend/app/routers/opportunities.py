from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..models.opportunity import Opportunity
from ..models.stage import PipelineStage
from ..models.audit import AuditLog
from ..models.activity import Activity
from ..core.permissions import get_current_user
from ..schemas.opportunity import OpportunityCreate, OpportunityUpdate, OpportunityResponse, MoveOpportunityRequest, PipelineResponse
import json

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

def to_response(opp: Opportunity, db: Session):
    client = db.query(Client).filter(Client.id == opp.client_id).first()
    owner = db.query(User).filter(User.id == opp.owner_id).first() if opp.owner_id else None
    stage = db.query(PipelineStage).filter(PipelineStage.id == opp.stage_id).first()
    return {
        "id": opp.id,
        "company_id": opp.company_id,
        "client_id": opp.client_id,
        "owner_id": opp.owner_id,
        "stage_id": opp.stage_id,
        "title": opp.title,
        "description": opp.description,
        "amount": opp.amount or 0,
        "probability": opp.probability,
        "expected_close_date": opp.expected_close_date,
        "source": opp.source,
        "next_action": opp.next_action,
        "loss_reason": opp.loss_reason,
        "tags": opp.tags,
        "created_at": opp.created_at,
        "updated_at": opp.updated_at,
        "weighted_amount": (opp.amount or 0) * (opp.probability or 0) / 100,
        "client_name": client.company_name if client else None,
        "owner_name": f"{owner.first_name} {owner.last_name}" if owner else None,
        "stage_name": stage.name if stage else None,
        "stage_color": stage.color if stage else None,
    }

@router.get("", response_model=List[OpportunityResponse])
def list_opportunities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = None,
    stage_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    source: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc"
):
    query = db.query(Opportunity).filter(Opportunity.company_id == current_user.company_id)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Opportunity.title.ilike(like), Opportunity.description.ilike(like)))
    if stage_id:
        query = query.filter(Opportunity.stage_id == stage_id)
    if owner_id:
        query = query.filter(Opportunity.owner_id == owner_id)
    if source:
        query = query.filter(Opportunity.source == source)
    if min_amount is not None:
        query = query.filter(Opportunity.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Opportunity.amount <= max_amount)
    order_col = getattr(Opportunity, sort_by, Opportunity.updated_at)
    if sort_order == "desc":
        order_col = order_col.desc()
    opps = query.order_by(order_col).all()
    return [to_response(o, db) for o in opps]

@router.get("/pipeline", response_model=PipelineResponse)
def get_pipeline(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), owner_id: Optional[int] = None, source: Optional[str] = None):
    stages = db.query(PipelineStage).filter(PipelineStage.company_id == current_user.company_id).order_by(PipelineStage.order).all()
    query = db.query(Opportunity).filter(Opportunity.company_id == current_user.company_id)
    if owner_id:
        query = query.filter(Opportunity.owner_id == owner_id)
    if source:
        query = query.filter(Opportunity.source == source)
    opportunities = query.all()
    
    total = sum(o.amount or 0 for o in opportunities)
    weighted = sum((o.amount or 0) * (o.probability or 0) / 100 for o in opportunities)
    
    stage_responses = []
    for s in stages:
        cnt = len([o for o in opportunities if o.stage_id == s.id])
        stage_responses.append({"id": s.id, "company_id": s.company_id, "name": s.name, "color": s.color, "order": s.order, "is_won": s.is_won, "is_lost": s.is_lost, "opportunities_count": cnt})
    
    return {
        "stages": stage_responses,
        "opportunities": [to_response(o, db) for o in opportunities],
        "total_value": total,
        "weighted_value": weighted
    }

@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    opps = db.query(Opportunity).filter(Opportunity.company_id == current_user.company_id).all()
    alerts = []
    now = datetime.now(timezone.utc)
    # stale: no activity for 14 days (using updated_at as proxy)
    for o in opps:
        stage = db.query(PipelineStage).filter(PipelineStage.id == o.stage_id).first()
        if stage and (stage.is_won or stage.is_lost):
            continue
        if o.updated_at and (now - o.updated_at.replace(tzinfo=timezone.utc) if o.updated_at.tzinfo is None else now - o.updated_at).days > 14:
            alerts.append({"type": "stale", "opportunity_id": o.id, "title": o.title, "message": f"Aucune activité depuis 14 jours", "stage_name": stage.name if stage else ""})
        if o.expected_close_date:
            from datetime import date
            if o.expected_close_date < date.today():
                alerts.append({"type": "overdue", "opportunity_id": o.id, "title": o.title, "message": f"Échéance dépassée: {o.expected_close_date}", "stage_name": stage.name if stage else ""})
        # blocked: Négociation sans next_action
        if not o.next_action and stage and stage.name.lower() in ["négociation", "negociation"]:
            alerts.append({"type": "blocked", "opportunity_id": o.id, "title": o.title, "message": "Affaire bloquée: aucune prochaine action définie"})
    return alerts

@router.post("", response_model=OpportunityResponse)
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # verify client belongs to company
    client = db.query(Client).filter(Client.id == payload.client_id, Client.company_id == current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    stage = db.query(PipelineStage).filter(PipelineStage.id == payload.stage_id, PipelineStage.company_id == current_user.company_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Étape non trouvée")
    
    data = payload.model_dump()
    data.pop("owner_id", None)
    opp = Opportunity(
        company_id=current_user.company_id,
        owner_id=payload.owner_id or current_user.id,
        **data
    )
    db.add(opp); db.commit(); db.refresh(opp)
    
    # automation: opportunity stage change notification (create activity log)
    # audit
    try:
        audit = AuditLog(company_id=current_user.company_id, user_id=current_user.id, action="create", entity_type="opportunity", entity_id=opp.id, details=json.dumps({"title": opp.title, "stage": stage.name}))
        db.add(audit); db.commit()
    except: pass
    
    return to_response(opp, db)

@router.get("/{opp_id}", response_model=OpportunityResponse)
def get_opportunity(opp_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id, Opportunity.company_id == current_user.company_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    return to_response(opp, db)

@router.put("/{opp_id}", response_model=OpportunityResponse)
def update_opportunity(opp_id: int, payload: OpportunityUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id, Opportunity.company_id == current_user.company_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    
    old_stage_id = opp.stage_id
    # if moving to won/lost stage, handle loss_reason requirement
    if payload.stage_id:
        new_stage = db.query(PipelineStage).filter(PipelineStage.id == payload.stage_id, PipelineStage.company_id == current_user.company_id).first()
        if not new_stage:
            raise HTTPException(status_code=404, detail="Étape cible non trouvée")
        if new_stage.is_lost and not payload.loss_reason and not opp.loss_reason:
            raise HTTPException(status_code=400, detail="Raison de perte obligatoire pour les opportunités perdues")
        if new_stage.is_won:
            opp.closed_at = datetime.now(timezone.utc)
        if new_stage.is_lost:
            opp.closed_at = datetime.now(timezone.utc)
    
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(opp, k, v)
    opp.updated_at = datetime.now(timezone.utc)
    opp.last_activity_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(opp)
    
    # notify owner if stage changed
    if old_stage_id != opp.stage_id:
        # create audit and potentially automation
        try:
            new_stage = db.query(PipelineStage).filter(PipelineStage.id == opp.stage_id).first()
            audit = AuditLog(company_id=current_user.company_id, user_id=current_user.id, action="stage_change", entity_type="opportunity", entity_id=opp.id, details=json.dumps({"from": old_stage_id, "to": opp.stage_id, "stage": new_stage.name if new_stage else ""}))
            db.add(audit); db.commit()
            # automation trigger: opportunity_stage_change
            from ..services.automation_service import trigger_automations
            trigger_automations(db, current_user.company_id, "opportunity_stage_change", {"opportunity_id": opp.id, "old_stage_id": old_stage_id, "new_stage_id": opp.stage_id})
        except Exception as e:
            print(f"automation error: {e}")
    
    return to_response(opp, db)

@router.post("/{opp_id}/move", response_model=OpportunityResponse)
def move_opportunity(opp_id: int, payload: MoveOpportunityRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id, Opportunity.company_id == current_user.company_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    stage = db.query(PipelineStage).filter(PipelineStage.id == payload.stage_id, PipelineStage.company_id == current_user.company_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Étape non trouvée")
    if stage.is_lost and not payload.loss_reason:
        raise HTTPException(status_code=400, detail="Raison de perte obligatoire")
    
    old_stage_id = opp.stage_id
    opp.stage_id = payload.stage_id
    if payload.loss_reason:
        opp.loss_reason = payload.loss_reason
    opp.updated_at = datetime.now(timezone.utc)
    if stage.is_won or stage.is_lost:
        opp.closed_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(opp)
    
    # automation
    try:
        from ..services.automation_service import trigger_automations
        trigger_automations(db, current_user.company_id, "opportunity_stage_change", {"opportunity_id": opp.id, "old_stage_id": old_stage_id, "new_stage_id": opp.stage_id})
    except: pass
    
    return to_response(opp, db)

@router.delete("/{opp_id}")
def delete_opportunity(opp_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id, Opportunity.company_id == current_user.company_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    db.delete(opp); db.commit()
    return {"message": "Opportunité supprimée"}
