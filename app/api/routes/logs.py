from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.utils.time_utils import format_datetime_gmt8

router = APIRouter(prefix="/logs", tags=["logs"])

LOG_LOOKBACK_MONTHS = 3

def _get_logs_date_range(db: Session) -> dict:
    row = (
        db.execute(
            text(
                """
                SELECT
                    now() - INTERVAL '3 months' AS date_from,
                    now() AS date_to
                """
            )
        )
        .mappings()
        .first()
    )

    if not row:
        return {
            "date_from": None, 
            "date_to": None, 
            "lookback_months": LOG_LOOKBACK_MONTHS,
        }
    
    return {
        "date_from": format_datetime_gmt8(row["date_from"]) if row["date_from"] else None, 
        "date_to": format_datetime_gmt8(row["date_to"]) if row["date_to"] else None,
        "lookback_months": LOG_LOOKBACK_MONTHS,
    }

@router.get("/overview")
def logs_overview(db: Session = Depends(get_db)):
    date_range = _get_logs_date_range(db)

    try:
        job_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        job_name,
                        status,
                        started_at,
                        finished_at,
                        details
                    FROM job_runs 
                    WHERE COALESCE(started_at, finished_at) >= now() - INTERVAL '3 months' 
                    ORDER BY started_at DESC NULLS LAST
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        job_rows = []

    job_runs = [
        {
            "id": str(r["id"]) if r["id"] is not None else None,
            "job_name": r["job_name"],
            "status": r["status"],
            "started_at": (
                format_datetime_gmt8(r["started_at"]) if r["started_at"] else None
            ),
            "finished_at": (
                format_datetime_gmt8(r["finished_at"]) if r["finished_at"] else None
            ),
            "details": r["details"],
        }
        for r in job_rows
    ]

    try:
        email_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        event_time,
                        user_name,
                        action,
                        target,
                        status_code,
                        details
                    FROM activity_logs
                    WHERE event_time >= now() - INTERVAL '3 months'
                        AND action IN ('Email sent', 'Email sending failed')
                    ORDER BY event_time DESC NULLS LAST
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        email_rows = []

    email_deliveries = [
        {
            "id": str(r["id"]) if r["id"] is not None else None,
            "event_time": (
                format_datetime_gmt8(r["event_time"]) if r["event_time"] else None
            ),
            "full_name": r["user_name"],
            "action": r["action"],
            "target": r["target"],
            "status_code": r["status_code"],
            "recipient": (r["details"] or {}).get("to_email") if r["details"] else None,
            "subject": (r["details"] or {}).get("subject") if r["details"] else None,
        }
        for r in email_rows
    ]

    try:
        onedrive_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        event_time,
                        user_name,
                        action,
                        target,
                        status_code,
                        details
                    FROM activity_logs
                    WHERE event_time >= now() - INTERVAL '3 months'
                        AND action IN ('OneDrive upload', 'OneDrive upload failed')
                    ORDER BY event_time DESC NULLS LAST
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        onedrive_rows = []

    onedrive_uploads = [
        {
            "id": str(r["id"]) if r["id"] is not None else None,
            "event_time": (
                format_datetime_gmt8(r["event_time"]) if r["event_time"] else None
            ),
            "full_name": r["user_name"],
            "action": r["action"],
            "target": r["target"],
            "status_code": r["status_code"],
            "category": (r["details"] or {}).get("category") if r["details"] else None,
            "dest_path": (r["details"] or {}).get("dest_path") if r["details"] else None,
        }
        for r in onedrive_rows
    ]

    try:
        activity_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        event_time,
                        event_type,
                        user_type,
                        user_name,
                        action,
                        target,
                        status_code
                    FROM activity_logs
                    WHERE event_time >= now() - INTERVAL '3 months'
                        AND event_type <> 'http_request'
                        AND action NOT IN (
                            'Email sent',
                            'Email sending failed',
                            'OneDrive upload',
                            'OneDrive upload failed',
                            'admin_view_fusionsolar_session_status'
                      )
                    ORDER BY event_time DESC NULLS LAST
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        activity_rows = []

    activity_logs = [
        {
            "id": str(r["id"]) if r["id"] is not None else None,
            "event_time": (
                format_datetime_gmt8(r["event_time"]) if r["event_time"] else None
            ),
            "event_type": r["event_type"],
            "full_name": r["user_name"],
            "action": r["action"],
            "target": r["target"],
            "status_code": r["status_code"],
        }
        for r in activity_rows
    ]

    return {
        "summary": {
            "lookback_months": LOG_LOOKBACK_MONTHS, 
            "date_from": date_range["date_from"], 
            "date_to": date_range["date_to"],
            "job_run_count": len(job_runs),
            "email_delivery_count": len(email_deliveries),
            "onedrive_upload_count": len(onedrive_uploads),
            "activity_log_count": len(activity_logs),
        },
        "job_runs": job_runs,
        "email_deliveries": email_deliveries,
        "onedrive_uploads": onedrive_uploads,
        "activity_logs": activity_logs,
    }