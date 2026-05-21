from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.auth import require_current_user
from app.db.session import get_db
from app.services.notification_service import (
    ensure_notifications_table, 
    format_relative_time,
)
from app.utils.time_utils import format_datetime_gmt8

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("")
def list_notifications(
    request: Request, 
    limit: int = Query(20, ge=1, le=100), 
    db: Session = Depends(get_db),
):
    current_user = require_current_user(request, db)
    user_id = str(current_user["id"])

    ensure_notifications_table(db)

    unread_count = (
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM notifications n
                LEFT JOIN notification_reads r
                    ON r.notification_id = n.id
                   AND r.user_id = CAST(:user_id AS uuid)
                WHERE r.notification_id IS NULL
                """
            ), 
            {"user_id": user_id},
        )
        .scalar_one()
    )

    rows = (
        db.execute(
            text(
                """
                SELECT
                    n.id,
                    n.notification_type,
                    n.title,
                    n.message,
                    n.target,
                    n.metadata,
                    n.created_at,
                    CASE
                        WHEN r.notification_id IS NULL THEN false
                        ELSE true
                    END AS is_read
                FROM notifications n
                LEFT JOIN notification_reads r
                    ON r.notification_id = n.id
                   AND r.user_id = CAST(:user_id AS uuid)
                ORDER BY n.created_at DESC
                LIMIT :limit
                """
            ), 
            {
                "user_id": user_id, 
                "limit": limit,
            },
        )
        .mappings()
        .all()
    )

    return {
        "unread_count": int(unread_count or 0), 
        "notifications": [
            {
                "id": str(row["id"]), 
                "notification_type": row["notification_type"], 
                "title": row["title"], 
                "message": row["message"],  
                "target": row["target"],  
                "metadata": row["metadata"],  
                "created_at": format_datetime_gmt8(row["created_at"]) if row["created_at"] else None, 
                "time_ago": format_relative_time(row["created_at"]), 
                "is_read": bool(row["is_read"])
            }
            for row in rows
        ],
    }

@router.post("/mark-all-read")
def mark_all_notifications_as_read(
    request: Request, 
    db: Session = Depends(get_db),
):
    current_user = require_current_user(request, db)
    user_id = str(current_user["id"])

    ensure_notifications_table(db)

    db.execute(
        text(
            """
            INSERT INTO notification_reads (
                notification_id,
                user_id,
                read_at
            )
            SELECT
                n.id,
                CAST(:user_id AS uuid),
                now()
            FROM notifications n
            LEFT JOIN notification_reads r
                ON r.notification_id = n.id
               AND r.user_id = CAST(:user_id AS uuid)
            WHERE r.notification_id IS NULL
            ON CONFLICT (notification_id, user_id)
            DO UPDATE SET read_at = EXCLUDED.read_at
            """
        ), 
        {"user_id": user_id},
    )

    db.commit()

    return {
        "message": "All notifications marked as read", 
        "unread_count": 0,
    }