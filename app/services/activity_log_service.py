from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session


def _to_json_or_none(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def resolve_user_name_from_request(request: Request | None) -> str | None:
    if request is None:
        return None

    try:
        session = getattr(request, "session", None)
        if session and isinstance(session, dict):
            user_name = session.get("user_name")
            if user_name:
                return str(user_name)
    except Exception:
        pass

    try:
        current_user = getattr(request.state, "current_user", None)
        if isinstance(current_user, dict):
            full_name = current_user.get("full_name")
            if full_name:
                return str(full_name)
    except Exception:
        pass

    return None


def log_activity(
    db: Session,
    *,
    event_type: str,
    action: str,
    user_type: str | None = None,
    user_name: str | None = None,
    target: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    details: Any = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO activity_logs (
                event_type,
                user_type,
                user_name,
                action,
                target,
                path,
                method,
                status_code,
                details
            )
            VALUES (
                :event_type,
                :user_type,
                :user_name,
                :action,
                :target,
                :path,
                :method,
                :status_code,
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "event_type": event_type,
            "user_type": user_type,
            "user_name": user_name,
            "action": action,
            "target": target,
            "path": path,
            "method": method,
            "status_code": status_code,
            "details": _to_json_or_none(details),
        },
    )
    db.commit()