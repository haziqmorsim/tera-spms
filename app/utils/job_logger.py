from __future__ import annotations
import json
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

def _to_json_or_none(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def start_run(db: Session, job_name: str, meta: Any = None):
    row = db.execute(
        text("""
            INSERT INTO job_runs (job_name, status, meta)
            VALUES (:job, 'running', CAST(:meta AS jsonb))
            RETURNING id
        """),
        {"job": job_name, "meta": _to_json_or_none(meta)},
    ).first()

    db.commit()
    return row[0]

def finish_run(db: Session, run_id: int, status: str, details: str | None = None, meta: Any = None,):
    db.execute(
        text("""
            UPDATE job_runs
            SET 
                finished_at = now(),
                status = :status,
                details = :details,
                meta = COALESCE(CAST(:meta AS jsonb), meta)
            WHERE id = :id
        """),
        {"id": run_id, "status": status, "details": details, "meta": _to_json_or_none(meta)},
    )
    db.commit()