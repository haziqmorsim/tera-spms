from __future__ import annotations
from datetime import date
from pathlib import Path
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.report_file_storage_service import (
    ensure_report_files_table,
    fetch_report_file_items,
    store_report_file_in_db,
)

EXCEL_REPORT_TYPES = {
    "ALARMS_XLSX",
    "ALARM_XLSX",
    "LOW_PSH_GENERATION_XLSX",
}

def fetch_excel_reports(limit: int = 50) -> list[dict]:
    db = SessionLocal()

    try:
        ensure_report_files_table(db)

        rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        report_type,
                        report_day,
                        file_name,
                        local_file_path,
                        onedrive_path,
                        onedrive_web_url,
                        created_at,
                        updated_at
                    FROM report_files
                    WHERE
                        (
                            upper(report_type) IN (
                                'ALARMS_XLSX',
                                'ALARM_XLSX',
                                'LOW_PSH_GENERATION_XLSX'
                            )
                            OR lower(file_name) LIKE 'alarms_report_%.xlsx'
                            OR lower(file_name) LIKE 'alarm_report_%.xlsx'
                            OR lower(file_name) LIKE 'low_psh_generation_report_%.xlsx'
                        )
                        AND lower(file_name) LIKE '%.xlsx'
                    ORDER BY report_day DESC NULLS LAST, updated_at DESC, created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

        reports = []

        for row in rows:
            item = dict(row)
            item["file_path"] = item.get("local_file_path") or item.get("onedrive_path")
            item["file_url"] = f"/api/reports/files/{item['id']}/download"
            item["download_url"] = item["file_url"]
            reports.append(item)

        return reports

    finally:
        db.close()

def _path_exists(value: str | None) -> bool:
    if not value:
        return False

    try:
        return Path(value).exists()

    except Exception:
        return False

def save_generated_report(
    report_type: str,
    file_path: str,
    report_day: date,
    local_file_path: str | None = None,
    onedrive_path: str | None = None,
    onedrive_web_url: str | None = None,
):
    db = SessionLocal()

    try:
        ensure_report_files_table(db)

        source_file_path = None

        if _path_exists(local_file_path):
            source_file_path = local_file_path
        elif _path_exists(file_path):
            source_file_path = file_path

        report_file_id = None

        if source_file_path:
            report_file_id = store_report_file_in_db(
                db,
                report_type=report_type,
                report_day=report_day,
                file_path=source_file_path,
                local_file_path=source_file_path,
                onedrive_path=onedrive_path
                or (file_path if file_path != source_file_path else None),
                onedrive_web_url=onedrive_web_url,
            )

        db.execute(
            text(
                """
                INSERT INTO generated_reports (
                    report_type,
                    report_day,
                    file_path,
                    local_file_path,
                    report_file_id,
                    generated_at
                )
                VALUES (
                    :type,
                    :day,
                    :path,
                    :local_path,
                    :report_file_id,
                    now()
                )
                """
            ),
            {
                "type": report_type,
                "day": report_day,
                "path": file_path,
                "local_path": local_file_path,
                "report_file_id": report_file_id,
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

def fetch_all_report_files(limit: int = 200) -> list[dict]:
    db = SessionLocal()

    try:
        return fetch_report_file_items(db, limit=limit)

    finally:
        db.close()