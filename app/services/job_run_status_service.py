from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Iterable
from sqlalchemy import text
from sqlalchemy.orm import Session

@dataclass(slots=True)
class JobRunStatus:
    job_name: str
    report_day: date
    exists: bool
    success: bool
    status: str | None
    started_at: object | None
    finished_at: object | None
    details: str | None

def get_latest_job_status_for_day(
    db: Session, 
    *, 
    job_names: str | Iterable[str], 
    report_day: date,
) -> JobRunStatus:
    if isinstance(job_names, str):
        job_name_list = [job_names]
    else:
        job_name_list = [str(name) for name in job_names]

    row = (
        db.execute(
            text(
                """
                SELECT
                    job_name,
                    status,
                    started_at,
                    finished_at,
                    details
                FROM job_runs
                WHERE job_name = ANY(:job_names)
                  AND DATE(started_at AT TIME ZONE 'Asia/Kuala_Lumpur') = :report_day
                ORDER BY started_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            ), 
            {
                "job_names": job_name_list, 
                "report_day": report_day,
            },
        )
        .mappings()
        .first()
    )

    display_job_name = job_name_list[0] if job_name_list else ""

    if not row:
        return JobRunStatus(
            job_name=display_job_name, 
            report_day= report_day, 
            exists=False, 
            success=False, 
            status=None, 
            started_at=None, 
            finished_at=None, 
            details=None,
        )
    
    status = str(row["status"] or "").strip().lower()

    return JobRunStatus(
        job_name=str(row["job_name"]), 
        report_day=report_day, 
        exists=True, 
        success=status == "success", 
        status=row["status"], 
        started_at=row["started_at"], 
        finished_at=row["finished_at"], 
        details=row["details"],
    )

def unsuccessful_message(task_label: str, report_day: date) -> str:
    return f"This {task_label} task for {report_day.strftime('%d-%m-%Y')} was unsuccessful."