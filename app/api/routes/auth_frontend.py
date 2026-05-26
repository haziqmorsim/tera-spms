from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.auth import get_current_user_from_session
from app.core.config import FRONTEND_BASE_URL
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.services.activity_log_service import log_activity
from app.services.password_reset_email_service import send_password_reset_email
from app.services.user_activity_service import (
    deactivate_inactive_users,
    mark_user_signed_in,
)

router = APIRouter(prefix="/auth", tags=["frontend-auth"])

PASSWORD_RESET_TOKEN_MINUTES = 30

class SignInPayload(BaseModel):
    email: EmailStr
    password: str

class SignUpPayload(BaseModel):
    full_name: str
    username: str
    email: EmailStr
    password: str
    confirm_password: str

class ForgotPasswordPayload(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    token: str
    password: str
    confirm_password: str

def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _ensure_password_reset_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id bigserial PRIMARY KEY,
                user_id uuid NOT NULL,
                token_hash text NOT NULL UNIQUE,
                expires_at timestamptz NOT NULL,
                used_at timestamptz,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token_hash
            ON password_reset_tokens (token_hash)
            """
        )
    )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id_created_at
            ON password_reset_tokens (user_id, created_at DESC)
            """
        )
    )

    db.commit()

def _password_validation_error(password: str, confirm_password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters."

    if len(password.encode("utf-8")) > 72:
        return "Password cannot be longer than 72 bytes."

    if password != confirm_password:
        return "Passwords do not match."

    return None

def _build_password_reset_url(request: Request, token: str) -> str:
    if FRONTEND_BASE_URL:
        base_url = FRONTEND_BASE_URL.rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")

    return f"{base_url}/reset-password.html?token={token}"

def _safe_user(row) -> dict:
    return {
        "id": str(row["id"]),
        "full_name": row["full_name"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
    }

@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)

    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {
        "authenticated": True,
        "user": {
            "id": str(current_user["id"]),
            "full_name": current_user["full_name"],
            "username": current_user["username"],
            "email": current_user["email"],
            "role": current_user["role"],
            "is_active": bool(current_user["is_active"]),
        },
    }

@router.post("/signin")
def signin(
    payload: SignInPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        valid = validate_email(str(payload.email), check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        raise HTTPException(status_code=400, detail="Invalid e-mail address.")

    deactivate_inactive_users(db)

    user = (
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
                WHERE lower(email) = lower(:email)
                LIMIT 1
                """
            ),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid e-mail or password.")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Your account is inactive.")

    mark_user_signed_in(db, str(user["id"]))

    request.session["user_id"] = str(user["id"])
    request.session["user_name"] = str(user["full_name"])
    request.session["user_username"] = str(user["username"])
    request.session["user_email"] = str(user["email"])
    request.session["user_role"] = str(user["role"])

    try:
        log_activity(
            db,
            event_type="User action",
            user_name=str(user["full_name"]),
            action="Login",
            target=str(user["email"]),
            path="/api/auth/signin",
            method="POST",
            status_code=200,
            details={"email": str(user["email"])},
        )
    except Exception:
        db.rollback()

    return {
        "message": "Signed in successfully.",
        "user": _safe_user(user),
    }

@router.post("/signup")
def signup(payload: SignUpPayload, db: Session = Depends(get_db)):
    full_name = payload.full_name.strip()
    username = payload.username.strip()

    try:
        valid = validate_email(str(payload.email), check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        raise HTTPException(status_code=400, detail="Invalid e-mail address.")

    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Full name must be at least 2 characters.")

    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters.")

    password_error = _password_validation_error(
        payload.password,
        payload.confirm_password,
    )

    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    existing_user = (
        db.execute(
            text(
                """
                SELECT id
                FROM app_users
                WHERE lower(email) = lower(:email)
                LIMIT 1
                """
            ),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="An account with this e-mail already exists.",
        )

    user_id = str(uuid4())

    db.execute(
        text(
            """
            INSERT INTO app_users (
                id,
                full_name,
                username,
                email,
                password_hash,
                role,
                is_active
            )
            VALUES (
                :id,
                :full_name,
                :username,
                :email,
                :password_hash,
                :role,
                :is_active
            )
            """
        ),
        {
            "id": user_id,
            "full_name": full_name,
            "username": username,
            "email": email,
            "password_hash": hash_password(payload.password),
            "role": "user",
            "is_active": True,
        },
    )

    db.commit()

    return {
        "message": "Account created successfully.",
    }

@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    _ensure_password_reset_table(db)

    generic_message = (
        "If an account with that e-mail exists, a password reset link has been sent."
    )

    try:
        valid = validate_email(str(payload.email), check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        return {"message": generic_message}

    user = (
        db.execute(
            text(
                """
                SELECT id, full_name, email, is_active
                FROM app_users
                WHERE lower(email) = lower(:email)
                LIMIT 1
                """
            ),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if not user or not user["is_active"]:
        return {"message": generic_message}

    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=PASSWORD_RESET_TOKEN_MINUTES
    )

    db.execute(
        text(
            """
            UPDATE password_reset_tokens
            SET used_at = now()
            WHERE user_id = :user_id
              AND used_at IS NULL
            """
        ),
        {"user_id": str(user["id"])},
    )

    db.execute(
        text(
            """
            INSERT INTO password_reset_tokens (
                user_id,
                token_hash,
                expires_at
            )
            VALUES (
                :user_id,
                :token_hash,
                :expires_at
            )
            """
        ),
        {
            "user_id": str(user["id"]),
            "token_hash": token_hash,
            "expires_at": expires_at,
        },
    )

    db.commit()

    reset_url = _build_password_reset_url(request, raw_token)

    send_password_reset_email(
        db,
        recipient_email=str(user["email"]),
        recipient_name=str(user["full_name"]),
        reset_url=reset_url,
    )

    return {"message": generic_message}

@router.post("/reset-password")
def reset_password(payload: ResetPasswordPayload, db: Session = Depends(get_db)):
    _ensure_password_reset_table(db)

    password_error = _password_validation_error(
        payload.password,
        payload.confirm_password,
    )

    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    token_hash = _hash_reset_token(payload.token)

    token_row = (
        db.execute(
            text(
                """
                SELECT
                    id,
                    user_id,
                    expires_at,
                    used_at
                FROM password_reset_tokens
                WHERE token_hash = :token_hash
                LIMIT 1
                """
            ),
            {"token_hash": token_hash},
        )
        .mappings()
        .first()
    )

    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    if token_row["used_at"] is not None:
        raise HTTPException(status_code=400, detail="This reset token has already been used.")

    now_utc = datetime.now(timezone.utc)

    if token_row["expires_at"] < now_utc:
        raise HTTPException(status_code=400, detail="This reset token has expired.")

    db.execute(
        text(
            """
            UPDATE app_users
            SET password_hash = :password_hash
            WHERE id = :user_id
            """
        ),
        {
            "password_hash": hash_password(payload.password),
            "user_id": str(token_row["user_id"]),
        },
    )

    db.execute(
        text(
            """
            UPDATE password_reset_tokens
            SET used_at = now()
            WHERE id = :token_id
            """
        ),
        {"token_id": token_row["id"]},
    )

    db.commit()

    return {"message": "Password has been reset successfully."}

@router.post("/signout")
def signout(request: Request):
    request.session.clear()
    return {"message": "Signed out successfully."}