from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.utils.time_utils import format_date_ddmmyyyy, now_gmt8, to_gmt8

def _to_json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    
    if isinstance(value, str):
        return value
    
    return json.dumps(value, ensure_ascii=False, default=str)

def ensure_notifications_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id bigserial PRIMARY KEY,
                notification_type text NOT NULL,
                title text NOT NULL,
                message text NOT NULL,
                target text,
                metadata jsonb,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS notification_reads (
                notification_id bigint NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
                user_id uuid NOT NULL,
                read_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (notification_id, user_id)
            )
            """
        )
    )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at
            ON notifications (created_at DESC)
            """
        )
    )

    db.execute(
        text(
             """
            CREATE INDEX IF NOT EXISTS idx_notification_reads_user_id
            ON notification_reads (user_id)
            """
        )
    )

    db.commit()

def create_notification(
    db: Session, 
    *, 
    notification_type: str, 
    title: str, 
    message: str, 
    target: str | None = None, 
    metadata: Any = None,
) -> None:
    ensure_notifications_table(db)

    db.execute(
        text(
            """
            INSERT INTO notifications (
                notification_type,
                title,
                message,
                target,
                metadata
            )
            VALUES (
                :notification_type,
                :title,
                :message,
                :target,
                CAST(:metadata AS jsonb)
            )
            """
        ), 
        {
            "notification_type": notification_type, 
            "title": title, 
            "message": message, 
            "target": target, 
            "metadata": _to_json_or_none(metadata),
        },
    )

    db.commit()

def _humanize_job_names(job_name: str) -> str:
    mapping = {
        "poll_alarms": "Poll alarms",
        "sync_high_temperature_inverters": "Sync high-temperature inverters",
        "detect_low_psh_plants_by_city": "Detect low-PSH plants by city",
        "detect_low_performing_plants_by_city": "Detect low-PSH plants by city",
        "detect_low_performing_inverters_by_plant": "Detect low-performing inverters by plant",
        "detect_low_performing_strings_by_inverter": "Detect low-performing strings by inverter",
        "generate_low_psh_generation_report": "Generate low-PSH generation report",
        "generate_troubleshooting_pdf": "Generate troubleshooting report",
        "email_daily_reports": "Daily reports e-mail",
        "deactivate_inactive_users": "Deactivate inactive users",
    }

    if job_name in mapping:
        return mapping[job_name]
    
    return job_name.replace("_", " ").strip().capitalize()

def notify_job_finished(
    db: Session, 
    *, 
    job_name: str, 
    status: str, 
    details: str | None = None, 
    metadata: Any = None,
) -> None:
    status_text = str(status or "").strip().lower()
    job_label = _humanize_job_names(job_name)

    if status_text == "success":
        message = f"{job_label} task has completed."
        title = "Task completed"
    elif status_text in ("fail", "failed", "error"):
        message = f"{job_label} task has failed."
        title = "Task failed"
    else:
        message = f"{job_label} task has finished with status: {status}."
        title = "Task finished"

    create_notification(
        db, 
        notification_type="task", 
        title=title, 
        message=message, 
        target=job_name, 
        metadata={
            "job_name": job_name, 
            "status": status, 
            "details": details, 
            "metadata": metadata,
        },
    )

def notify_report_generated(
    db: Session, 
    *, 
    report_type: str, 
    report_day, 
    file_path: str | None = None,
) -> None:
    normalized_type = str(report_type or "").strip().upper()
    report_day_text = format_date_ddmmyyyy(report_day) if report_day else None

    if normalized_type in {"TROUBLESHOOTING_PDF", "TROUBLESHOOTING_REPORT_PDF"}:
        message = (
            f"Troubleshooting report for {report_day_text} has been generated." 
            if report_day_text 
            else "Troubleshooting report has been generated."
        )
        title = "Troubleshooting report generated"

    elif normalized_type in {"MONTHLY_XLSX", "MONTHLY_PDF", "MONTHLY_REPORT_XLSX", "MONTHLY_REPORT_PDF"}:
        message = (
            f"Monthly report for {report_day_text} has been generated."
            if report_day_text 
            else "Monthly report has been generated."
        )

    else:
        return
    
    create_notification(
        db, 
        notification_type="report", 
        title=title, 
        message=message, 
        target=file_path, 
        metadata={
            "report_type": report_type, 
            "report_day": str(report_day) if report_day else None, 
            "file_path": file_path,
        },
    )

def notify_email_service(
    db: Session,
    *, 
    subject: str,
    to_email: str | None = None, 
    attachment_paths: list[str] | None = None,
) -> None:
    subject_text = str(subject or "").strip()

    if "daily reports" in subject_text.lower():
        message = "Daily reports e-mail has been sent."
        title = "Daily reports e-mail sent"
    else:
        message = "E-mail has been sent."
        title = "E-mail sent"

    create_notification(
        db, 
        notification_type="email", 
        title=title, 
        message=message, 
        target=subject_text, 
        metadata={
            "subject": subject_text, 
            "to_email": to_email, 
            "attachment_paths": attachment_paths or [],
        },
    )

def format_relative_time(value: datetime | None) -> str:
    if value is None:
        return ""
    
    value_gmt8 = to_gmt8(value)
    current = now_gmt8()

    if value_gmt8 is None:
        return ""
    
    seconds = int((current - value_gmt8).total_seconds())

    if seconds < 0:
        seconds = 0

    if seconds < 60:
        return "Just now"
    
    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m ago"
    
    hours = minutes // 60

    if hours < 24:
        return f"{hours}h ago"
    
    days = hours // 24
    
    return f"{days}d ago"