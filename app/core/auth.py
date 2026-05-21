from __future__ import annotations
from fastapi import HTTPException, Request, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db

def get_current_user_from_session(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    
    row = (
        db.execute(text("""
            SELECT id, full_name, username, email, role, is_active, created_at 
            FROM app_users 
            WHERE id = :user_id 
            LIMIT 1
        """),
        {"user_id": user_id},
        ).mappings().first()
    )

    if not row:
        request.session.clear()
        return None
    
    if not row["is_active"]:
        return None
    
    return dict(row)

def is_admin_user(user: dict | None) -> bool:
    if not user:
        return False
    return str(user.get("role") or "").strip().lower() == "admin"

def require_current_user(request: Request, db: Session) -> dict:
    current_user = get_current_user_from_session(request, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return current_user

def require_admin_user(request: Request, db: Session) -> dict:
    current_user = require_current_user(request, db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user