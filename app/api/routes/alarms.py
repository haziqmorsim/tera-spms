from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.deps import get_db

router = APIRouter()


@router.get("")
def list_alarms(
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if active_only:
        rows = (
            db.execute(
                text(
                    """
            SELECT * 
            FROM alarms 
            WHERE is_active = true 
            ORDER BY occurrence_ts DESC 
            LIMIT :limit
        """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )
    else:
        rows = (
            db.execute(
                text(
                    """
                SELECT * 
                FROM alarms 
                ORDER BY occurrence_ts DESC 
                LIMIT :limit
            """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [dict(r) for r in rows]


@router.get("/summary")
def alarm_summary(db: Session = Depends(get_db)):
    rows = (
        db.execute(
            text(
                """
            SELECT severity, COUNT(*)::int AS count 
            FROM alarms 
            WHERE is_active = true 
            GROUP BY severity
            ORDER BY severity 
        """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]
