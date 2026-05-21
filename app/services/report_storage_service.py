from __future__ import annotations
from datetime import date
from sqlalchemy import text
from app.db.session import SessionLocal

EXCEL_REPORT_TYPES = {
    "ALARMS_XLSX",
    "ALARM_XLSX",
    "LOW_PSH_GENERATION_XLSX",
}

def fetch_excel_reports(limit: int = 50) -> list[dict]:
    db = SessionLocal()

    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        report_type,
                        report_day,
                        file_path,
                        local_file_path,
                        created_at
                    FROM generated_reports
                    WHERE
                        (
                            upper(report_type) IN (
                                'ALARMS_XLSX',
                                'ALARM_XLSX',
                                'LOW_PSH_GENERATION_XLSX'
                            )
                            OR replace(local_file_path, '\\', '/') ILIKE 'reports/excel/alarms/%'
                            OR replace(local_file_path, '\\', '/') ILIKE 'reports/excel/overall/%'
                            OR replace(file_path, '\\', '/') ILIKE 'reports/excel/alarms/%'
                            OR replace(file_path, '\\', '/') ILIKE 'reports/excel/overall/%'
                        )
                        AND lower(coalesce(local_file_path, file_path, '')) LIKE '%.xlsx'
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

        return [dict(row) for row in rows]

    finally:
        db.close()

def save_generated_report(
    report_type: str,
    file_path: str,
    report_day: date,
    local_file_path: str | None = None,
):
    db = SessionLocal()

    try:
        db.execute(
            text(
                """
                INSERT INTO generated_reports (
                    report_type,
                    report_day,
                    file_path,
                    local_file_path,
                    generated_at
                )
                VALUES (
                    :type,
                    :day,
                    :path,
                    :local_path,
                    now()
                )
                """
            ),
            {
                "type": report_type,
                "day": report_day,
                "path": file_path,
                "local_path": local_file_path,
            },
        )

        try:
            from app.services.notification_service import notify_report_generated

            notify_report_generated(
                db,
                report_type=report_type,
                report_day=report_day,
                file_path=file_path,
            )
        except Exception:
            db.rollback()
            raise

        db.commit()

    finally:
        db.close()