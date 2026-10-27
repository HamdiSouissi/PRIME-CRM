from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date

class DashboardStats(BaseModel):
    prospects_count: int = 0
    clients_count: int = 0
    opportunities_count: int = 0
    opportunities_won: int = 0
    opportunities_lost: int = 0
    pipeline_value: float = 0
    weighted_pipeline_value: float = 0
    signed_revenue: float = 0
    forecast_revenue: float = 0
    conversion_rate: float = 0
    avg_cycle_days: float = 0
    avg_deal_amount: float = 0
    quotes_created: int = 0
    quotes_accepted: int = 0
    quotes_refused: int = 0
    quotes_expired: int = 0
    overdue_tasks: int = 0
    upcoming_meetings: int = 0

class ChartDataPoint(BaseModel):
    name: str
    value: float
    count: Optional[int] = None

class DashboardResponse(BaseModel):
    stats: DashboardStats
    pipeline_by_stage: List[ChartDataPoint] = []
    revenue_by_month: List[Dict[str, Any]] = []
    opportunities_by_source: List[ChartDataPoint] = []
    performance_by_owner: List[Dict[str, Any]] = []
    recent_activities: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []
