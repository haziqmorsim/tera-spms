from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from email_validator import validate_email, EmailNotValidError
from app.db.session import get_db
from app.core.security import hash_password, verify_password
from app.core.auth import get_current_user_from_session
from app.services.activity_log_service import log_activity
from app.services.password_reset_email_service import send_password_reset_email
from app.services.user_activity_service import (deactivate_inactive_users, mark_user_signed_in)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PASSWORD_RESET_TOKEN_MINUTES = 30

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

def _build_password_reset_url(request: Request, token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/reset-password?token={token}"

def _password_validation_error(password: str, confirmPassword: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    
    if len(password.encode("utf-8")) > 72:
        return "Password cannot be longer than 72 bytes."
    
    if password != confirmPassword:
        return "Password do not match."
    
    return None

@router.get("/signin")
def signin_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    signup_success = request.query_params.get("signup") == "success"
    reset_success = request.query_params.get("reset") == "success"

    return templates.TemplateResponse(
        "signin.html",
        {
            "request": request,
            "error": None,
            "signup_success": signup_success, 
            "reset-success": reset_success,
        },
    )

@router.post("/signin")
def signin_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        valid = validate_email(email, check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "Invalid e-mail address.",
                "signup_success": False, 
                "reset_success": False,
            },
            status_code=400,
        )
    
    deactivate_inactive_users(db)

    user = (
        db.execute(
            text(
                """
                SELECT id, full_name, username, email, role, is_active, password_hash
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

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "Invalid e-mail or password.",
                "signup_success": False, 
                "reset_success": False,
            },
            status_code=401,
        )

    if not user["is_active"]:
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "Your account is inactive.",
                "signup_success": False, 
                "reset_success": False,
            },
            status_code=403,
        )
    
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
            path="/signin",
            method="POST",
            status_code=303,
            details={"email": str(user["email"])},
        )
    except Exception:
        db.rollback()

    return RedirectResponse(url="/", status_code=303)


@router.get("/signup")
def signup_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "error": None,
        },
    )


@router.post("/signup")
def signup_submit(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    full_name = full_name.strip()
    username = username.strip()
    email = email.strip()

    if len(full_name) < 2:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": "Full name must be at least 2 characters.",
            },
            status_code=400,
        )

    if len(username) < 2:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": "Username must be at least 2 characters.",
            },
            status_code=400,
        )

    try:
        valid = validate_email(email, check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": "Invalid e-mail address.",
            },
            status_code=400,
        )
    
    password_error  = _password_validation_error(password, confirm_password)
    if password_error:
        return templates.TemplateResponse(
            "signup.html", 
            {
                "request": request, 
                "error": password_error,
            }, 
            status_code=400,
        )

    # if len(password) < 8:
    #     return templates.TemplateResponse(
    #         "signup.html",
    #         {
    #             "request": request,
    #             "error": "Password must be at least 8 characters.",
    #         },
    #         status_code=400,
    #     )

    # if password != confirm_password:
    #     return templates.TemplateResponse(
    #         "signup.html",
    #         {
    #             "request": request,
    #             "error": "Passwords do not match.",
    #         },
    #         status_code=400,
    #     )

    existing_user = (
        db.execute(
            text(
                """
                SELECT id
                FROM app_users
                WHERE lower(email) = lower(:email)
                """
            ),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if existing_user:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": "An account with this e-mail already exists.",
            },
            status_code=409,
        )

    user_id = str(uuid4())
    password_hash = hash_password(password)

    db.execute(
        text(
            """
            INSERT INTO app_users (
                id, full_name, username, email, password_hash, role, is_active
            )
            VALUES (
                :id, :full_name, :username, :email, :password_hash, :role, :is_active
            )
            """
        ),
        {
            "id": user_id,
            "full_name": full_name,
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "role": "user",
            "is_active": True,
        },
    )
    db.commit()

    return RedirectResponse(url="/signin?signup=success", status_code=303)

@router.get("/forgot-password")
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_session(request, db)
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={
            "error": None,
            "message": None,
        },
    )

@router.post("/forgot-password")
def forgot_password_submit(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    _ensure_password_reset_table(db)

    generic_message = ("If that account with that e-mail exists, a password reset link has been sent.")

    try:
        valid = validate_email(email, check_deliverability=False)
        email = valid.normalized
    except EmailNotValidError:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": None,
                "message": generic_message,
            },
            status_code=200,
        )
    
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
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": None,
                "message": generic_message,
            },
            status_code=200,
        )
    
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_MINUTES)

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

    try:
        send_password_reset_email(
            db, 
            recipient_email=(user["email"]), 
            recipient_name=(user["full_name"]), 
            reset_url=reset_url,
        )

        try:
            log_activity(
                db, 
                event_type="User action", 
                user_type="system", 
                user_name=None, 
                action="Request password reset", 
                target=str(user["email"]), 
                path="/forgot-password", 
                method="POST", 
                status_code=200, 
                details={"email": str(user["email"])},
            )
        except Exception:
            db.rollback()

    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": f"Failed to send reset e-mail: {exc}",
                "message": None,
            },
            status_code=500,
        )
    
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={
            "error": None,
            "message": generic_message,
        }, 
        status_code=200,
    )

@router.get("/reset-password")
def reset_password_page(
    request: Request,
    token: str = "",
    db: Session = Depends(get_db),
):
    current_user = get_current_user_from_session(request, db)
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    _ensure_password_reset_table(db)

    token_hash = _hash_reset_token(token) if token else ""

    reset_token = (
        db.execute(
            text(
                """
                SELECT id, user_id, expires_at, used_at
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

    token_valid = False

    if reset_token and not reset_token["used_at"]:
        expires_at = reset_token["expires_at"]

        if expires_at and expires_at > datetime.now(timezone.utc):
            token_valid = True

    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={
            "token": token,
            "token_valid": token_valid,
            "error": None,
        },
    )

@router.post("/reset-password")
def reset_password_submit(
    request: Request, 
    token: str = Form(...), 
    password: str = Form(...), 
    confirm_password: str = Form(...), 
    db: Session = Depends(get_db)
):
    _ensure_password_reset_table(db)

    password_error = _password_validation_error(password, confirm_password)

    if password_error:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={
                "token": token,
                "token_valid": True,
                "error": password_error,
            }, 
            status_code=400,
        )
    
    token_hash = _hash_reset_token(token)

    reset_token = (
        db.execute(
            text(
                """
                SELECT id, user_id, expires_at, used_at
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

    if not reset_token or reset_token["used_at"]:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={
                "token": token,
                "token_valid": False,
                "error": "This password reset link is invalid or has already been used.",
            }, 
            status_code=400,
        )
    
    expires_at = reset_token["expires_at"]

    if not expires_at or expires_at <= datetime.now(timezone.utc):
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={
                "token": token,
                "token_valid": False,
                "error": "This password reset link has expired. Please request a new one.",
            }, 
            status_code=400,
        )
    
    new_password_hash = hash_password(password)

    db.execute(
        text(
             """
            UPDATE app_users
            SET password_hash = :password_hash
            WHERE id = :user_id
            """
        ), 
        {
            "password_hash": new_password_hash, 
            "user_id": str(reset_token["user_id"]),
        },
    )

    db.execute(
        text(
            """
            UPDATE password_reset_tokens
            SET used_at = now()
            WHERE user_id = :user_id
              AND used_at IS NULL
              AND id <> :token_id
            """
        ),
        {
            "user_id": str(reset_token["user_id"]), 
            "token_id": reset_token["id"],
        },
    )

    db.commit()

    try:
        user = (
            db.execute(
                text(
                    """
                    SELECT full_name, email
                    FROM app_users
                    WHERE id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": str(reset_token["user_id"])},
            )
            .mappings()
            .first()
        )

        log_activity(
            db, 
            event_type="User action", 
            user_type="system", 
            user_name=user["full_name"] if user else None, 
            action="Reset password", 
            target=user["email"] if user else str(reset_token["user_id"]), 
            path="/reset-password", 
            method="POST", 
            status_code=300, 
            details={"user_id": str(reset_token["user_id"])},
        )
    except Exception:
        db.rollback()

    return RedirectResponse(url="/signin?reset=success", status_code=303)

@router.get("/signout")
def signout(request: Request, db: Session = Depends(get_db)):
    user_name = request.session.get("user_name")
    user_email = request.session.get("user_email")

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user" if user_name else "system",
            user_name=user_name,
            action="Logout",
            target=user_email,
            path="/signout",
            method="GET",
            status_code=303,
            details={"email": user_email},
        )
    except Exception:
        db.rollback()

    request.session.clear()
    return RedirectResponse(url="/signin", status_code=303)