from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models.user import User
from ..models.stage import PipelineStage
from ..core.permissions import get_current_user, require_admin
from ..schemas.opportunity import StageCreate, StageUpdate, StageResponse
from ..services.redis_store import RedisStore, get_redis_store

router = APIRouter(prefix="/stages", tags=["pipeline"])

@router.get("", response_model=List[StageResponse])
def list_stages(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stages = db.query(PipelineStage).filter(PipelineStage.company_id == current_user.company_id).order_by(PipelineStage.order).all()
    result = []
    for s in stages:
        count = len(s.opportunities) if hasattr(s, 'opportunities') else 0
        result.append({"id": s.id, "company_id": s.company_id, "name": s.name, "color": s.color, "order": s.order, "is_won": s.is_won, "is_lost": s.is_lost, "opportunities_count": count})
    return result

@router.post("", response_model=StageResponse)
def create_stage(payload: StageCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin), store: RedisStore | None = Depends(get_redis_store)):
    stage = PipelineStage(company_id=current_user.company_id, **payload.model_dump())
    db.add(stage); db.commit(); db.refresh(stage)
    if store is not None:
        store.invalidate_stages(current_user.company_id)
    return {"id": stage.id, "company_id": stage.company_id, "name": stage.name, "color": stage.color, "order": stage.order, "is_won": stage.is_won, "is_lost": stage.is_lost, "opportunities_count": 0}

@router.put("/{stage_id}", response_model=StageResponse)
def update_stage(stage_id: int, payload: StageUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin), store: RedisStore | None = Depends(get_redis_store)):
    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id, PipelineStage.company_id == current_user.company_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Étape non trouvée")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(stage, k, v)
    db.commit(); db.refresh(stage)
    if store is not None:
        store.invalidate_stages(current_user.company_id)
    return {"id": stage.id, "company_id": stage.company_id, "name": stage.name, "color": stage.color, "order": stage.order, "is_won": stage.is_won, "is_lost": stage.is_lost, "opportunities_count": len(stage.opportunities)}

@router.delete("/{stage_id}")
def delete_stage(stage_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin), store: RedisStore | None = Depends(get_redis_store)):
    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id, PipelineStage.company_id == current_user.company_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Étape non trouvée")
    if stage.opportunities:
        raise HTTPException(status_code=400, detail="Impossible de supprimer une étape contenant des opportunités")
    db.delete(stage); db.commit()
    if store is not None:
        store.invalidate_stages(current_user.company_id)
    return {"message": "Étape supprimée"}

@router.post("/reorder")
def reorder_stages(payload: List[int], db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    for idx, sid in enumerate(payload):
        stage = db.query(PipelineStage).filter(PipelineStage.id == sid, PipelineStage.company_id == current_user.company_id).first()
        if stage:
            stage.order = idx + 1
    db.commit()
    return {"message": "Ordre mis à jour"}
