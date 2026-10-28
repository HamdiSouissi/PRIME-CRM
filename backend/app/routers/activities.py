from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from datetime import datetime, timezone, date
from ..database import get_db
from ..models.user import User
from ..models.activity import Activity
from ..models.client import Client
from ..core.permissions import get_current_user
from ..schemas.activity import ActivityCreate, ActivityUpdate, ActivityResponse

router = APIRouter(prefix="/activities", tags=["activities"])

def to_response(act: Activity, db: Session):
    client = db.query(Client).filter(Client.id == act.client_id).first() if act.client_id else None
    owner = db.query(User).filter(User.id == act.owner_id).first() if act.owner_id else None
    return {
        "id": act.id,
        "company_id": act.company_id,
        "owner_id": act.owner_id,
        "client_id": act.client_id,
        "opportunity_id": act.opportunity_id,
        "type": act.type,
        "title": act.title,
        "description": act.description,
        "status": act.status,
        "priority": act.priority,
        "due_date": act.due_date,
        "due_time": act.due_time,
        "duration_minutes": act.duration_minutes,
        "location": act.location,
        "is_completed": act.is_completed,
        "created_at": act.created_at,
        "updated_at": act.updated_at,
        "client_name": client.company_name if client else None,
        "owner_name": f"{owner.first_name} {owner.last_name}" if owner else None
    }

@router.get("", response_model=List[ActivityResponse])
def list_activities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    owner_id: Optional[int] = None,
    client_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    due_from: Optional[date] = None,
    due_to: Optional[date] = None,
    view: Optional[str] = None,  # day, week, month
    date_filter: Optional[date] = None
):
    query = db.query(Activity).filter(Activity.company_id == current_user.company_id)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Activity.title.ilike(like), Activity.description.ilike(like)))
    if type:
        query = query.filter(Activity.type == type)
    if status:
        query = query.filter(Activity.status == status)
    if priority:
        query = query.filter(Activity.priority == priority)
    if owner_id:
        query = query.filter(Activity.owner_id == owner_id)
    if client_id:
        query = query.filter(Activity.client_id == client_id)
    if opportunity_id:
        query = query.filter(Activity.opportunity_id == opportunity_id)
    if due_from:
        query = query.filter(Activity.due_date >= due_from)
    if due_to:
        query = query.filter(Activity.due_date <= due_to)
    
    if view and date_filter:
        # calendar view filters
        if view == "day":
            query = query.filter(Activity.due_date == date_filter)
        elif view == "week":
            from datetime import timedelta
            start = date_filter - timedelta(days=date_filter.weekday())
            end = start + timedelta(days=6)
            query = query.filter(Activity.due_date >= start, Activity.due_date <= end)
        elif view == "month":
            start = date_filter.replace(day=1)
            # next month
            if start.month == 12:
                end = start.replace(year=start.year+1, month=1, day=1) - timedelta(days=1)
            else:
                end = start.replace(month=start.month+1, day=1) - timedelta(days=1)
            query = query.filter(Activity.due_date >= start, Activity.due_date <= end)
    
    activities = query.order_by(Activity.due_date.asc(), Activity.created_at.desc()).all()
    return [to_response(a, db) for a in activities]

@router.get("/overdue")
def get_overdue(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date.today()
    overdue = db.query(Activity).filter(
        Activity.company_id == current_user.company_id,
        Activity.due_date < today,
        Activity.is_completed == False,
        Activity.status != "cancelled"
    ).all()
    return [to_response(a, db) for a in overdue]

@router.get("/upcoming")
def get_upcoming(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date.today()
    from datetime import timedelta
    upcoming = db.query(Activity).filter(
        Activity.company_id == current_user.company_id,
        Activity.due_date >= today,
        Activity.due_date <= today + timedelta(days=7),
        Activity.is_completed == False
    ).order_by(Activity.due_date.asc()).limit(10).all()
    return [to_response(a, db) for a in upcoming]

@router.post("", response_model=ActivityResponse)
def create_activity(payload: ActivityCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    activity = Activity(
        company_id=current_user.company_id,
        owner_id=payload.owner_id or current_user.id,
        **payload.model_dump(exclude={"owner_id"})
    )
    # set owner explicitly
    if payload.owner_id:
        activity.owner_id = payload.owner_id
    else:
        activity.owner_id = current_user.id
    db.add(activity); db.commit(); db.refresh(activity)
    return to_response(activity, db)

@router.get("/{activity_id}", response_model=ActivityResponse)
def get_activity(activity_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    act = db.query(Activity).filter(Activity.id == activity_id, Activity.company_id == current_user.company_id).first()
    if not act:
        raise HTTPException(status_code=404, detail="Activité non trouvée")
    return to_response(act, db)

@router.put("/{activity_id}", response_model=ActivityResponse)
def update_activity(activity_id: int, payload: ActivityUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    act = db.query(Activity).filter(Activity.id == activity_id, Activity.company_id == current_user.company_id).first()
    if not act:
        raise HTTPException(status_code=404, detail="Activité non trouvée")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(act, k, v)
    if payload.is_completed:
        act.completed_at = datetime.now(timezone.utc)
        act.status = "done"
        act.is_completed = True
    elif payload.is_completed == False:
        act.completed_at = None
        act.is_completed = False
    act.updated_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(act)
    return to_response(act, db)

@router.post("/{activity_id}/complete")
def complete_activity(activity_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    act = db.query(Activity).filter(Activity.id == activity_id, Activity.company_id == current_user.company_id).first()
    if not act:
        raise HTTPException(status_code=404, detail="Activité non trouvée")
    act.is_completed = not act.is_completed
    act.status = "done" if act.is_completed else "todo"
    act.completed_at = datetime.now(timezone.utc) if act.is_completed else None
    db.commit()
    return {"is_completed": act.is_completed, "status": act.status}

@router.delete("/{activity_id}")
def delete_activity(activity_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    act = db.query(Activity).filter(Activity.id == activity_id, Activity.company_id == current_user.company_id).first()
    if not act:
        raise HTTPException(status_code=404, detail="Activité non trouvée")
    db.delete(act); db.commit()
    return {"message": "Activité supprimée"}
