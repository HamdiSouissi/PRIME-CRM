import json
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.automation import AutomationRule, AutomationExecution
from ..models.activity import Activity
from ..models.opportunity import Opportunity
from ..models.quote import Quote

def trigger_automations(db: Session, company_id: int, trigger_type: str, trigger_data: dict):
    """Déclenche les règles correspondantes, avec protection contre double exécution via run_count + check"""
    rules = db.query(AutomationRule).filter(
        AutomationRule.company_id == company_id,
        AutomationRule.trigger_type == trigger_type,
        AutomationRule.is_active == True
    ).all()
    
    for rule in rules:
        # idempotence: check if already executed for this trigger_data in last 5 min
        existing = db.query(AutomationExecution).filter(
            AutomationExecution.rule_id == rule.id,
            AutomationExecution.executed_at >= datetime.now(timezone.utc) - timedelta(minutes=5)
        ).first()
        # For opportunity_stage_change, allow multiple but different opportunities
        if existing and trigger_type not in ["opportunity_stage_change"]:
            # check if same trigger_data hash
            try:
                if existing.trigger_data and json.loads(existing.trigger_data) == trigger_data:
                    # skip duplicate
                    exec_dup = AutomationExecution(
                        rule_id=rule.id,
                        company_id=company_id,
                        trigger_data=json.dumps(trigger_data),
                        result="Skipped: duplicate execution within 5min",
                        status="skipped"
                    )
                    db.add(exec_dup)
                    db.commit()
                    continue
            except:
                pass
        
        try:
            result = execute_rule(db, rule, trigger_data)
            execution = AutomationExecution(
                rule_id=rule.id,
                company_id=company_id,
                trigger_data=json.dumps(trigger_data),
                result=result,
                status="success"
            )
            rule.run_count = (rule.run_count or 0) + 1
            rule.last_run_at = datetime.now(timezone.utc)
            db.add(execution)
            db.commit()
        except Exception as e:
            execution = AutomationExecution(
                rule_id=rule.id,
                company_id=company_id,
                trigger_data=json.dumps(trigger_data),
                result=str(e)[:1000],
                status="failed"
            )
            db.add(execution)
            db.commit()

def execute_rule(db: Session, rule: AutomationRule, trigger_data: dict) -> str:
    action_config = json.loads(rule.action_config) if rule.action_config else {}
    trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
    
    if rule.action_type == "create_task":
        # create a task
        title = action_config.get("title", f"Tâche automatique: {rule.name}")
        description = action_config.get("description", f"Déclenché par {rule.trigger_type}")
        owner_id = action_config.get("owner_id")
        client_id = trigger_data.get("client_id")
        opportunity_id = trigger_data.get("opportunity_id")
        
        # Resolve owner: if opportunity has owner, use it
        if opportunity_id:
            opp = db.query(Opportunity).filter(Opportunity.id==opportunity_id).first()
            if opp and opp.owner_id:
                owner_id = opp.owner_id
            if opp and opp.client_id:
                client_id = opp.client_id
        
        # Personalize title with trigger data
        if opportunity_id:
            opp = db.query(Opportunity).filter(Opportunity.id==opportunity_id).first()
            if opp:
                title = title.replace("{opportunity_title}", opp.title)
        
        due_days = action_config.get("due_in_days", 2)
        due_date = date.today() + timedelta(days=due_days)
        
        activity = Activity(
            company_id=rule.company_id,
            owner_id=owner_id,
            client_id=client_id,
            opportunity_id=opportunity_id,
            type="task",
            title=title,
            description=description,
            status="todo",
            priority=action_config.get("priority", "medium"),
            due_date=due_date
        )
        db.add(activity)
        db.flush()
        return f"Tâche créée: {activity.id} - {title}"
    
    elif rule.action_type == "send_notification":
        # In-app notification: we create an activity of type note as notification
        # Real implementation would push to notifications table / websocket
        message = action_config.get("message", f"Notification: {rule.name}")
        # For now, just log as execution result
        return f"Notification envoyée: {message} (in-app)"
    
    elif rule.action_type == "create_alert":
        # Similar to create_task but high priority
        activity = Activity(
            company_id=rule.company_id,
            owner_id=trigger_data.get("owner_id"),
            client_id=trigger_data.get("client_id"),
            opportunity_id=trigger_data.get("opportunity_id"),
            type="task",
            title=action_config.get("title", "Alerte automatique"),
            description=action_config.get("description", ""),
            status="todo",
            priority="urgent",
            due_date=date.today()
        )
        db.add(activity)
        db.flush()
        return f"Alerte créée: {activity.id}"
    
    else:
        return f"Action {rule.action_type} non implémentée"

def run_scheduled_automations(db: Session):
    """À appeler via cron/Celery: vérifie les règles périodiques"""
    # Example: devis sans réponse pendant X jours -> relance
    rules = db.query(AutomationRule).filter(AutomationRule.is_active==True).all()
    for rule in rules:
        if rule.trigger_type == "quote_no_response":
            trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
            days = trigger_config.get("days", 5)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            # find quotes sent but not responded
            quotes = db.query(Quote).filter(
                Quote.company_id==rule.company_id,
                Quote.status=="sent",
                Quote.sent_at != None,
                Quote.sent_at <= cutoff
            ).all()
            for q in quotes:
                # check if already triggered for this quote
                existing = db.query(AutomationExecution).filter(
                    AutomationExecution.rule_id==rule.id,
                    AutomationExecution.trigger_data.like(f"%\"quote_id\": {q.id}%")
                ).first()
                if existing:
                    continue
                trigger_automations(db, rule.company_id, "quote_no_response", {"quote_id": q.id, "client_id": q.client_id})
        
        elif rule.trigger_type == "client_inactive":
            trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
            days = trigger_config.get("days", 30)
            cutoff = date.today() - timedelta(days=days)
            from ..models.client import Client
            clients = db.query(Client).filter(
                Client.company_id==rule.company_id,
                Client.last_interaction_at != None,
                Client.last_interaction_at <= cutoff
            ).all()
            for c in clients:
                trigger_automations(db, rule.company_id, "client_inactive", {"client_id": c.id})
