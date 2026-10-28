"""Cache only stage outcome IDs; PostgreSQL remains the source of truth."""

from sqlalchemy.orm import Session

from ..models.stage import PipelineStage
from .redis_store import RedisStore


def stage_outcome_ids(db: Session, company_id: int, store: RedisStore | None) -> tuple[list[int], list[int]]:
    if store is not None:
        cached = store.get_stage_outcomes(company_id)
        if cached is not None:
            return cached

    stages = db.query(PipelineStage.id, PipelineStage.is_won, PipelineStage.is_lost).filter(
        PipelineStage.company_id == company_id
    ).all()
    won = [stage.id for stage in stages if stage.is_won]
    lost = [stage.id for stage in stages if stage.is_lost]
    if store is not None:
        store.set_stage_outcomes(company_id, won, lost)
    return won, lost
