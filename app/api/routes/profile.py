from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.auth import require_current_user
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.services.activity_log_service import log_activity
from app.services.user_activity_service import ensure_user_activity_columns
from app.utils.time_utils import format_datetime_gmt8

router = APIRouter(prefix="/profile", tags=["profile"])

class ProfileUpdatePayload(BaseModel):
    full_name: str = Field(min_length=2)
    username: str = Field(min_length=2)
    email: EmailStr
    current_password: str | None = None
    new_password: str | None = None
    confirm_new_password: str | None = None

def _password_change_requested(payload: ProfileUpdatePayload) -> bool:
    return any(
        [
            payload.current_password, 
            payload.new_password, 
            payload.confirm_new_password,
        ]
    )

def _validate_password_change(payload: ProfileUpdatePayload) -> None:
    if not _password_change_requested(payload):
        return
    
    if not payload.current_password:
        return HTTPException(
            status_code=400, 
            detail="Current password is required to change your password.",
        )
    
    if not payload.new_password:
        raise HTTPException(
            status_code=400, 
            detail="New password is required.",
        )
    
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=400, 
            detail="New password must be at least 8 characters.",
        )
    
    if len(payload.new_password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400, 
            detail="New password cannot be longer than 72 bytes.",
        )
    
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=400, 
            detail="New passwords do not match.",
        )
    
@router.get("")
def get_profile(
    request: Request, 
    db: Session = Depends(get_db),
):
    current_user = require_current_user(request, db)
    ensure_user_activity_columns(db)

    row = (
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
                    created_at
                FROM app_users
                WHERE id = :user_id
                LIMIT 1
                """
            ), 
            {"user_id": str(current_user["id"])},
        )
        .mappings()
        .first()
    )

    if not row:
        request.session.clear()
        raise HTTPException(
            status_code=401, 
            detail="Not authenticated",
        )
    
    return {
        "user": {
            "id": str(row["id"]), 
            "full_name": row["full_name"], 
            "username": row["username"], 
            "email": row["email"], 
            "role": row["role"], 
            "is_active": bool(row["is_active"]), 
            "last_signin_at": format_datetime_gmt8(row["last_signin_at"]) if row["last_signin_at"] else None, 
            "created_at": format_datetime_gmt8(row["created_at"]) if row["created_at"] else None,
        }
    }

@router.put("")
def update_profile(
    payload: ProfileUpdatePayload, 
    request: Request, 
    db: Session = Depends(get_db),
):
    current_user = require_current_user(request, db)
    ensure_user_activity_columns(db)

    user_id = str(current_user["id"])

    full_name = payload.full_name.strip()
    username = payload.username.strip()
    email = str(payload.email).strip()

    if len(full_name) < 2:
        raise HTTPException(
            status_code=400, 
            detail="Full name must be at least 2 characters.",
        )
    
    if len(username) < 2:
        raise HTTPException(
            status_code=400, 
            detail="Username must be at least 2 characters.",
        )
    
    existing_user = (
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
                    password_hash
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

    if not existing_user:
        request.session.clear()
        raise HTTPException(
            status_code=401, 
            detail="Not authenticated",
        )
    
    duplicate = (
        db.execute(
            text(
                """
                SELECT id
                FROM app_users
                WHERE (
                    lower(email) = lower(:email)
                    OR lower(username) = lower(:username)
                )
                  AND id <> :user_id
                LIMIT 1
                """
            ), 
            {
                "email": email, 
                "username": username, 
                "user_id": user_id,
            },
        )
        .mappings()
        .first()
    )

    if duplicate:
        raise HTTPException(
            status_code=409, 
            detail="The e-mail or username has been taken.",
        )
    
    _validate_password_change(payload)

    update_password = _password_change_requested(payload)

    if update_password:
        if not verify_password(
            payload.current_password or "", 
            existing_user["password_hash"],
        ):
            raise HTTPException(
                status_code=400, 
                detail="Current password is incorrect.",
            )
        
        db.execute(
            text(
                """
                UPDATE app_users
                SET
                    full_name = :full_name,
                    username = :username,
                    email = :email,
                    password_hash = :password_hash
                WHERE id = :user_id
                """
            ), 
            {
                "user_id": user_id, 
                "full_name": full_name, 
                "username": username, 
                "email": email, 
                "password_hash": hash_password(payload.new_password or ""),
            },
        )
    else:
        db.execute(
            text(
                """
                UPDATE app_users
                SET
                    full_name = :full_name,
                    username = :username,
                    email = :email
                WHERE id = :user_id
                """
            ), 
            {
                "user_id": user_id, 
                "full_name": full_name, 
                "username": username, 
                "email": email,
            },
        )

    db.commit()

    request.session["user_name"] = full_name
    request.session["user_username"] = username
    request.session["user_email"] = email
    
    try:
        log_activity(
            db, 
            event_type="User action", 
            user_name=full_name, 
            action="Update profile", 
            target=email, 
            path="/api/profile", 
            method="PUT", 
            status_code=200, 
            details={
                "user_id": user_id, 
                "full_name": full_name, 
                "username": username, 
                "email": email, 
                "password_changed": update_password,
            },
        )
    except Exception:
        db.rollback()

    return {
        "message": "Profile updated successfully.", 
        "user": {
            "id": user_id, 
            "full_name": full_name, 
            "username": username, 
            "email": email, 
            "role": existing_user["role"], 
            "is_active": bool(existing_user["is_active"]),
        },
    }