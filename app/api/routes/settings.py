from __future__ import annotations
import os
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.auth import require_admin_user
from app.db.session import get_db
from app.services.activity_log_service import log_activity
from app.services.user_activity_service import ensure_user_activity_columns
from app.services.fusionsolar_session_service import (
    delete_fusionsolar_session_file,
    get_fusionsolar_session_status,
)
from app.utils.time_utils import format_datetime_gmt8

router = APIRouter(prefix="/settings", tags=["settings"])

class UserUpdatePayload(BaseModel):
    full_name: str = Field(min_length=2)
    username: str = Field(min_length=2)
    email: EmailStr
    role: str
    is_active: bool

class EmailSettingsPayload(BaseModel):
    email_delivery_method: str = "graph"
    graph_tenant_id: str
    graph_client_id: str
    graph_client_secret: str
    graph_sender_email: EmailStr
    email_to: str

class ReportSettingsPayload(BaseModel):
    low_psh_underperformance_pct: float
    low_psh_threshold: float
    temp_threshold_c: float
    low_string_current_threshold_pct: float
    string_current_start_time: str
    string_current_end_time: str

def _ensure_settings_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key text PRIMARY KEY,
                setting_value text,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.commit()

def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = (
        db.execute(
            text(
                """
                SELECT setting_value
                FROM app_settings
                WHERE setting_key = :key
                LIMIT 1
                """
            ),
            {"key": key},
        )
        .mappings()
        .first()
    )
    if not row:
        return default
    return row["setting_value"] or default

def _set_setting(db: Session, key: str, value: Any) -> None:
    db.execute(
        text(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES (:key, :value, now())
            ON CONFLICT (setting_key)
            DO UPDATE SET
                setting_value = EXCLUDED.setting_value,
                updated_at = now()
            """
        ),
        {"key": key, "value": "" if value is None else str(value)},
    )

def _validate_hhmm_time(value: str, field_name: str) -> str:
    cleaned = str(value or "").strip()

    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")
    
    try:
        hour_text, minute_text = cleaned.split(":")
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field_name} must use HH:MM format.",)
    
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid 24-hour time.",)
    
    return f"{hour:02d}:{minute:02d}"

@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    ensure_user_activity_columns(db)

    rows = (
        db.execute(
            text(
                """
                SELECT
                    id,
                    full_name,
                    username,
                    email,
                    role,
                    is_active,
                    last_signin_at,
                    deactivated_at,
                    deactivation_reason,
                    created_at
                FROM app_users
                ORDER BY created_at ASC NULLS LAST, full_name ASC
                """
            )
        )
        .mappings()
        .all()
    )

    return {
        "users": [
            {
                "id": str(r["id"]),
                "full_name": r["full_name"],
                "username": r["username"],
                "email": r["email"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "last_signin_at": format_datetime_gmt8(r["last_signin_at"]) if r["last_signin_at"] else None,
                "deactivated_at": format_datetime_gmt8(r["deactivated_at"]) if r["deactivated_at"] else None,
                "deactivation_reason": r["deactivation_reason"],
                "created_at": format_datetime_gmt8(r["created_at"]) if r["created_at"] else None,
            }
            for r in rows
        ]
    }

@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdatePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    admin_user = require_admin_user(request, db)

    role_value = payload.role.strip().lower()
    if role_value not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Role must be either admin or user.")

    existing = (
        db.execute(
            text(
                """
                SELECT id
                FROM app_users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="User not found.")

    duplicate = (
        db.execute(
            text(
                """
                SELECT id
                FROM app_users
                WHERE (lower(email) = lower(:email) OR lower(username) = lower(:username))
                  AND id <> :user_id
                LIMIT 1
                """
            ),
            {
                "email": str(payload.email),
                "username": payload.username,
                "user_id": user_id,
            },
        )
        .mappings()
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="Another user already has this e-mail or username.",
        )

    db.execute(
        text(
            """
            UPDATE app_users
            SET
                full_name = :full_name,
                username = :username,
                email = :email,
                role = :role,
                is_active = :is_active
            WHERE id = :user_id
            """
        ),
        {
            "user_id": user_id,
            "full_name": payload.full_name.strip(),
            "username": payload.username.strip(),
            "email": str(payload.email).strip(),
            "role": role_value,
            "is_active": payload.is_active,
        },
    )
    db.commit()

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user",
            user_name=admin_user["full_name"],
            action="Update user",
            target=payload.full_name.strip(),
            path=f"/api/settings/users/{user_id}",
            method="PUT",
            status_code=200,
            details={
                "updated_user_id": str(user_id),
                "updated_full_name": payload.full_name.strip(),
                "updated_username": payload.username.strip(),
                "updated_email": str(payload.email).strip(),
                "updated_role": role_value,
                "updated_is_active": payload.is_active,
            },
        )
    except Exception:
        db.rollback()

    return {"message": "User updated successfully."}

@router.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    admin_user = require_admin_user(request, db)

    current_session_user_id = str(request.session.get("user_id") or "")
    if current_session_user_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    existing = (
        db.execute(
            text(
                """
                SELECT id, full_name, email
                FROM app_users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="User not found.")

    db.execute(
        text("DELETE FROM app_users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    db.commit()

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user",
            user_name=admin_user["full_name"],
            action="Delete user",
            target=existing["full_name"],
            path=f"/api/settings/users/{user_id}",
            method="DELETE",
            status_code=200,
            details={
                "deleted_full_name": existing["full_name"],
                "deleted_email": existing["email"],
            },
        )
    except Exception:
        db.rollback()

    return {"message": "User deleted successfully."}

@router.get("/email")
def get_email_settings(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    _ensure_settings_table(db)

    graph_client_secret = _get_setting(
        db,
        "graph_client_secret",
        os.getenv("GRAPH_CLIENT_SECRET", ""),
    )

    return {
        "email_delivery_method": _get_setting(
            db,
            "email_delivery_method",
            os.getenv("EMAIL_DELIVERY_METHOD", "graph"),
        ),
        "graph_tenant_id": _get_setting(
            db,
            "graph_tenant_id",
            os.getenv("GRAPH_TENANT_ID", ""),
        ),
        "graph_client_id": _get_setting(
            db,
            "graph_client_id",
            os.getenv("GRAPH_CLIENT_ID", ""),
        ),
        "graph_client_secret": "****************" if graph_client_secret else "",
        "graph_sender_email": _get_setting(
            db,
            "graph_sender_email",
            os.getenv("GRAPH_SENDER_EMAIL", os.getenv("EMAIL_FROM", "")),
        ),
        "email_to": _get_setting(
            db,
            "email_to",
            os.getenv("EMAIL_TO", ""),
        ),
    }


@router.put("/email")
def update_email_settings(
    payload: EmailSettingsPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    admin_user = require_admin_user(request, db)
    _ensure_settings_table(db)

    delivery_method = payload.email_delivery_method.strip().lower()
    if delivery_method != "graph":
        raise HTTPException(status_code=400, detail="Only Microsoft Graph is supported.")

    _set_setting(db, "email_delivery_method", delivery_method)
    _set_setting(db, "graph_tenant_id", payload.graph_tenant_id.strip())
    _set_setting(db, "graph_client_id", payload.graph_client_id.strip())
    _set_setting(db, "graph_sender_email", str(payload.graph_sender_email).strip())
    _set_setting(db, "email_from", str(payload.graph_sender_email).strip())
    _set_setting(db, "email_to", payload.email_to.strip())

    if payload.graph_client_secret.strip() and payload.graph_client_secret.strip() != "********":
        _set_setting(db, "graph_client_secret", payload.graph_client_secret.strip())

    db.commit()

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user",
            user_name=admin_user["full_name"],
            action="Update email settings",
            target="email_settings_graph",
            path="/api/settings/email",
            method="PUT",
            status_code=200,
            details={
                "email_delivery_method": delivery_method,
                "graph_tenant_id": payload.graph_tenant_id.strip(),
                "graph_client_id": payload.graph_client_id.strip(),
                "graph_sender_email": str(payload.graph_sender_email).strip(),
                "email_to": payload.email_to.strip(),
            },
        )
    except Exception:
        db.rollback()

    return {"message": "Email settings updated successfully."}

@router.get("/reports")
def get_report_settings(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    _ensure_settings_table(db)

    return {
        "low_psh_underperformance_pct": float(
            _get_setting(
                db,
                "low_psh_underperformance_pct",
                os.getenv("LOW_PSH_UNDERPERFORMANCE_PCT", "10"),
            )
            or 10
        ),
        "low_psh_threshold": float(
            _get_setting(
                db, 
                "low_psh_threshold", 
                os.getenv("LOW_PSH_ABSOLUTE_THRESHOLD", "3"),
            )
            or 3
        ),
        "temp_threshold_c": float(
            _get_setting(
                db, "temp_threshold_c", 
                os.getenv("TEMP_THRESHOLD_C", "70"),
            )
            or 70
        ),
        "low_string_current_threshold_pct": float(
            _get_setting(
                db, 
                "low_string_current_threshold_pct", 
                os.getenv("LOW_STRING_CURRENT_THRESHOLD_PCT", "20"),
            )
            or 20
        ),
        "string_current_start_time": _get_setting(
                db, 
                "string_current_start_time", 
                os.getenv("STRING_CURRENT_START_TIME", "07:30"),
            ),
        "string_current_end_time": _get_setting(
                db, 
                "string_current_end_time", 
                os.getenv("STRING_CURRENT_END_TIME", "19:30"),
            ),
    }

@router.put("/reports")
def update_report_settings(
    payload: ReportSettingsPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    admin_user = require_admin_user(request, db)
    _ensure_settings_table(db)

    string_current_start_time = _validate_hhmm_time(
        payload.string_current_start_time, 
        "String current start time",
    )

    string_current_end_time = _validate_hhmm_time(
        payload.string_current_end_time, 
        "String current end time",
    )

    if payload.low_string_current_threshold_pct < 0:
        raise HTTPException(
            status_code=400, 
            detail="Low string current threshold percentage cannot be negative.",
        )

    _set_setting(db, "low_psh_underperformance_pct", payload.low_psh_underperformance_pct)
    _set_setting(db, "low_psh_threshold", payload.low_psh_threshold)
    _set_setting(db, "temp_threshold_c", payload.temp_threshold_c)
    _set_setting(db, "low_string_current_threshold_pct", payload.low_string_current_threshold_pct)
    _set_setting(db, "string_current_start_time", payload.string_current_start_time)
    _set_setting(db, "string_current_end_time", payload.string_current_end_time)
    db.commit()

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user",
            user_name=admin_user["full_name"],
            action="Update report settings",
            target="report_settings",
            path="/api/settings/reports",
            method="PUT",
            status_code=200,
            details={
                "low_psh_underperformance_pct": payload.low_psh_underperformance_pct,
                "low_psh_threshold": payload.low_psh_threshold,
                "temp_threshold_c": payload.temp_threshold_c,
                "low_string_current_threshold_pct": payload.low_string_current_threshold_pct, 
                "string_current_start_time": payload.string_current_start_time, 
                "string_current_end_time": payload.string_current_end_time,
            },
        )
    except Exception:
        db.rollback()

    return {"message": "Report settings updated successfully."}

@router.get("/fusionsolar-session")
def get_fusionsolar_session(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    return get_fusionsolar_session_status()

@router.delete("/fusionsolar-session")
def delete_fusionsolar_session(
    request: Request,
    db: Session = Depends(get_db),
):
    admin_user = require_admin_user(request, db)
    result = delete_fusionsolar_session_file()

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user",
            user_name=admin_user["full_name"],
            action="Delete FusionSolar session",
            target="fusionsolar_state.json",
            path="/api/settings/fusionsolar-session",
            method="DELETE",
            status_code=200,
            details=result,
        )
    except Exception:
        db.rollback()

    return result