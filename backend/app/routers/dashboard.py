from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timezone, date, timedelta
from typing import Optional
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..models.opportunity import Opportunity
from ..models.stage import PipelineStage
from ..models.activity import Activity
from ..models.quote import Quote
from ..core.permissions import get_current_user
from ..schemas.dashboard import DashboardStats, DashboardResponse
from ..services.redis_store import RedisStore, get_redis_store
from ..services.stage_cache import stage_outcome_ids

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    store: RedisStore | None = Depends(get_redis_store),
    period: str = Query("month", regex="^(week|month|quarter|year|all)$"),
    owner_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    company_id = current_user.company_id
    
    # Date range
    today = date.today()
    if not start_date or not end_date:
        if period == "week":
            start_date = today - timedelta(days=7)
            end_date = today
        elif period == "month":
            start_date = today.replace(day=1)
            end_date = today
        elif period == "quarter":
            q = (today.month -1)//3
            start_date = date(today.year, q*3+1, 1)
            end_date = today
        elif period == "year":
            start_date = date(today.year, 1, 1)
            end_date = today
        elif period == "all":
            start_date = date(2000,1,1)
            end_date = today
    
    # Clients
    prospects_count = db.query(Client).filter(Client.company_id == company_id, Client.type == "prospect", Client.is_archived==False).count()
    clients_count = db.query(Client).filter(Client.company_id == company_id, Client.type == "client", Client.is_archived==False).count()
    
    # Opportunities
    opp_query = db.query(Opportunity).filter(Opportunity.company_id == company_id)
    if owner_id:
        opp_query = opp_query.filter(Opportunity.owner_id == owner_id)
    # A short-lived, encrypted cache stores IDs only, scoped to this company.
    # The cache is never used to authorize a request or mutate an opportunity.
    won_stage_ids, lost_stage_ids = stage_outcome_ids(db, company_id, store)
    
    opportunities = opp_query.all()
    opportunities_count = len(opportunities)
    opportunities_won = len([o for o in opportunities if o.stage_id in won_stage_ids])
    opportunities_lost = len([o for o in opportunities if o.stage_id in lost_stage_ids])
    pipeline_value = sum(o.amount or 0 for o in opportunities if o.stage_id not in won_stage_ids and o.stage_id not in lost_stage_ids)
    weighted_pipeline_value = sum((o.amount or 0)*(o.probability or 0)/100 for o in opportunities if o.stage_id not in won_stage_ids and o.stage_id not in lost_stage_ids)
    
    # Revenue: won opportunities amount
    signed_revenue = sum(o.amount or 0 for o in opportunities if o.stage_id in won_stage_ids)
    forecast_revenue = weighted_pipeline_value + signed_revenue
    
    # Conversion
    total_closed = opportunities_won + opportunities_lost
    conversion_rate = (opportunities_won / total_closed * 100) if total_closed else 0
    
    # Avg cycle: average days between created_at and closed_at for won
    won_opps = [o for o in opportunities if o.stage_id in won_stage_ids and o.closed_at and o.created_at]
    avg_cycle_days = 0
    if won_opps:
        total_days = sum((o.closed_at.replace(tzinfo=None) - o.created_at.replace(tzinfo=None)).days for o in won_opps)
        avg_cycle_days = total_days / len(won_opps)
    
    avg_deal_amount = (sum(o.amount or 0 for o in opportunities) / len(opportunities)) if opportunities else 0
    
    # Quotes
    quotes = db.query(Quote).filter(Quote.company_id == company_id).all()
    quotes_created = len(quotes)
    quotes_accepted = len([q for q in quotes if q.status == "accepted"])
    quotes_refused = len([q for q in quotes if q.status == "refused"])
    quotes_expired = len([q for q in quotes if q.status == "expired"])
    
    # Tasks
    overdue_tasks = db.query(Activity).filter(Activity.company_id==company_id, Activity.due_date < today, Activity.is_completed==False, Activity.status!="cancelled").count()
    upcoming_meetings = db.query(Activity).filter(Activity.company_id==company_id, Activity.type=="meeting", Activity.due_date >= today, Activity.due_date <= today + timedelta(days=7)).count()
    
    stats = DashboardStats(
        prospects_count=prospects_count,
        clients_count=clients_count,
        opportunities_count=opportunities_count,
        opportunities_won=opportunities_won,
        opportunities_lost=opportunities_lost,
        pipeline_value=round(pipeline_value,2),
        weighted_pipeline_value=round(weighted_pipeline_value,2),
        signed_revenue=round(signed_revenue,2),
        forecast_revenue=round(forecast_revenue,2),
        conversion_rate=round(conversion_rate,2),
        avg_cycle_days=round(avg_cycle_days,1),
        avg_deal_amount=round(avg_deal_amount,2),
        quotes_created=quotes_created,
        quotes_accepted=quotes_accepted,
        quotes_refused=quotes_refused,
        quotes_expired=quotes_expired,
        overdue_tasks=overdue_tasks,
        upcoming_meetings=upcoming_meetings
    )
    
    # Pipeline by stage
    stages = db.query(PipelineStage).filter(PipelineStage.company_id==company_id).order_by(PipelineStage.order).all()
    pipeline_by_stage = []
    for s in stages:
        opps_in_stage = [o for o in opportunities if o.stage_id == s.id]
        pipeline_by_stage.append({"name": s.name, "value": sum(o.amount or 0 for o in opps_in_stage), "count": len(opps_in_stage)})
    
    # Revenue by month (last 6 months)
    revenue_by_month = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -=1
        count = len([o for o in opportunities if o.created_at and o.created_at.year == y and o.created_at.month == m])
        amount = sum(o.amount or 0 for o in opportunities if o.created_at and o.created_at.year == y and o.created_at.month == m and o.stage_id in won_stage_ids)
        revenue_by_month.append({"month": f"{y}-{m:02d}", "revenue": amount, "count": count})
    
    # By source
    sources = {}
    for o in opportunities:
        src = o.source or "Non défini"
        sources[src] = sources.get(src, 0) + (o.amount or 0)
    opportunities_by_source = [{"name": k, "value": v, "count": len([x for x in opportunities if (x.source or "Non défini")==k])} for k,v in sources.items()]
    
    # Performance by owner
    owners = db.query(User).filter(User.company_id==company_id).all()
    performance_by_owner = []
    for u in owners:
        user_opps = [o for o in opportunities if o.owner_id == u.id]
        performance_by_owner.append({
            "owner": f"{u.first_name} {u.last_name}",
            "opportunities": len(user_opps),
            "won": len([o for o in user_opps if o.stage_id in won_stage_ids]),
            "revenue": sum(o.amount or 0 for o in user_opps if o.stage_id in won_stage_ids),
            "pipeline": sum(o.amount or 0 for o in user_opps if o.stage_id not in won_stage_ids and o.stage_id not in lost_stage_ids)
        })
    
    # Recent activities
    recent = db.query(Activity).filter(Activity.company_id==company_id).order_by(Activity.created_at.desc()).limit(5).all()
    recent_activities = [{"id": a.id, "title": a.title, "type": a.type, "due_date": a.due_date, "status": a.status} for a in recent]
    
    # Alerts
    alerts = []
    for o in opportunities:
        stage = next((s for s in stages if s.id == o.stage_id), None)
        if stage and (stage.is_won or stage.is_lost):
            continue
        if o.updated_at and (datetime.now(timezone.utc) - o.updated_at.replace(tzinfo=timezone.utc) if o.updated_at.tzinfo is None else datetime.now(timezone.utc) - o.updated_at).days > 14:
            alerts.append({"type": "stale", "message": f"Opportunité '{o.title}' sans activité depuis 14 jours"})
        if o.expected_close_date and o.expected_close_date < today:
            alerts.append({"type": "overdue", "message": f"Opportunité '{o.title}' échéance dépassée"})
    
    return {
        "stats": stats,
        "pipeline_by_stage": pipeline_by_stage,
        "revenue_by_month": revenue_by_month,
        "opportunities_by_source": opportunities_by_source,
        "performance_by_owner": performance_by_owner,
        "recent_activities": recent_activities,
        "alerts": alerts[:10]
    }

@router.get("/export")
def export_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), format: str = "csv"):
    # simple csv export of opportunities
    import csv, io
    from fastapi.responses import StreamingResponse
    opportunities = db.query(Opportunity).filter(Opportunity.company_id==current_user.company_id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Titre","Client","Montant","Probabilité","Montant pondéré","Étape","Source","Date"])
    for o in opportunities:
        client = db.query(Client).filter(Client.id==o.client_id).first()
        stage = db.query(PipelineStage).filter(PipelineStage.id==o.stage_id).first()
        writer.writerow([o.id, o.title, client.company_name if client else "", o.amount, o.probability, round((o.amount or 0)*(o.probability or 0)/100,2), stage.name if stage else "", o.source, o.created_at])
    output.seek(0)
    return StreamingResponse(io.StringIO(output.getvalue()), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=dashboard-export.csv"})
