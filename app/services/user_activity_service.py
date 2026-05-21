from __future__ import annotations
import os
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

INACTIVE_USER_DAYS = int(os.getenv("INACTIVE_USER_DAYS", "30"))

INACTIVE_USER_EXCLUDE_ADMINS = (os.getenv("INACTIVE_USER_EXCLUDE_ADMINS", "true").strip().lower() 
                                in {"1", "true", "yes", "y"})

def ensure_user_activity_columns(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE app_users
            ADD COLUMN IF NOT EXISTS last_signin_at timestamptz
            """
        )
    )

    db.execute(
        text(
           """
            ALTER TABLE app_users
            ADD COLUMN IF NOT EXISTS deactivated_at timestamptz
            """ 
        )
    )

    db.execute(
        text(
            """
            ALTER TABLE app_users
            ADD COLUMN IF NOT EXISTS deactivation_reason text
            """
        )
    )

    db.commit()

def mark_user_signed_in(db: Session, user_id: str) -> None:
    ensure_user_activity_columns(db)

    db.execute(
        text(
            """
            UPDATE app_users
            SET
                last_signin_at = now(),
                deactivation_reason = NULL
            WHERE id = :user_id
            """
        ), 
        {"user_id": user_id},
    )

    db.commit()

def deactivate_inactive_users(
    db: Session, 
    *, 
    inactive_days: int = INACTIVE_USER_DAYS, 
    exclude_admins: bool = INACTIVE_USER_EXCLUDE_ADMINS,
) -> list[dict[str, Any]]:
    ensure_user_activity_columns(db)

    reason = f"Not signed in for {inactive_days} days."

    rows = (
        db.execute(
            text(
                """
                    UPDATE app_users
                    SET
                        is_active = false,
                        deactivated_at = now(),
                        deactivation_reason = :reason
                    WHERE is_active = true
                    AND COALESCE(last_signin_at, created_at) IS NOT NULL
                    AND COALESCE(last_signin_at, created_at) < now() - (:inactive_days * INTERVAL '1 day')
                    AND (
                            :exclude_admins = false
                            OR lower(role) <> 'admin'
                    )
                    RETURNING
                        id,
                        full_name,
                        username,
                        email,
                        role,
                        last_signin_at,
                        deactivated_at,
                        deactivation_reason
                    """
            ), 
            {
                "inactive_days": inactive_days, 
                "exclude_admins": exclude_admins, 
                "reason": reason,
            },
        )
        .mappings()
        .all()
    )
    db.commit()

    return [dict(row) for row in rows]