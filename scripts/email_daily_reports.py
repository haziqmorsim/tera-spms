from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.email_service import send_email_with_attachments
from app.services.onedrive_service import upload_file_to_onedrive
from app.services.report_path_service import (
    EXCEL_ALARMS_DIR,
    EXCEL_OVERALL_DIR,
    TROUBLESHOOTING_REPORTS_DIR,
    ensure_report_directories,
)
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import format_date_ddmmyyyy, today_gmt8

load_dotenv()

JOB_NAME = "email_daily_reports"

def _latest_matching_file(
    directory: Path,
    *,
    prefix: str,
    suffix: str,
    report_day_text: str | None = None,
) -> Path | None:
    if not directory.exists():
        return None

    matches = [
        file
        for file in directory.iterdir()
        if file.is_file()
        and file.name.lower().startswith(prefix.lower())
        and file.suffix.lower() == suffix.lower()
    ]

    if not matches:
        return None

    if report_day_text:
        today_matches = [
            file
            for file in matches
            if report_day_text in file.name
        ]

        if today_matches:
            today_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return today_matches[0]

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]

def find_required_daily_reports() -> dict[str, Path]:
    ensure_report_directories()

    report_day = today_gmt8()
    report_day_text = report_day.strftime("%d-%m-%Y")

    low_psh_generation_file = _latest_matching_file(
        EXCEL_OVERALL_DIR,
        prefix="low_psh_generation_report_",
        suffix=".xlsx",
        report_day_text=report_day_text,
    )

    alarms_file = _latest_matching_file(
        EXCEL_ALARMS_DIR,
        prefix="alarms_report_",
        suffix=".xlsx",
        report_day_text=report_day_text,
    )

    troubleshooting_file = _latest_matching_file(
        TROUBLESHOOTING_REPORTS_DIR,
        prefix="troubleshooting_report_",
        suffix=".pdf",
        report_day_text=report_day_text,
    )

    missing: list[str] = []

    if low_psh_generation_file is None:
        missing.append(
            f"{EXCEL_OVERALL_DIR.as_posix()}/low_psh_generation_report_{report_day_text}.xlsx"
        )

    if alarms_file is None:
        missing.append(
            f"{EXCEL_ALARMS_DIR.as_posix()}/alarms_report_{report_day_text}.xlsx"
        )

    if troubleshooting_file is None:
        missing.append(
            f"{TROUBLESHOOTING_REPORTS_DIR.as_posix()}/troubleshooting_report_{report_day_text}.pdf"
        )

    if missing:
        raise FileNotFoundError(
            "Required daily report file(s) not found:\n- " + "\n- ".join(missing)
        )

    return {
        "low_psh_generation": low_psh_generation_file,
        "alarms": alarms_file,
        "troubleshooting": troubleshooting_file,
    }

def upload_required_reports_to_onedrive(
    reports: dict[str, Path],
) -> dict[str, str]:
    report_day = today_gmt8()

    low_psh_generation_onedrive_path = upload_file_to_onedrive(
        source_path=reports["low_psh_generation"],
        category="excel",
        report_day=report_day,
    )

    alarms_onedrive_path = upload_file_to_onedrive(
        source_path=reports["alarms"],
        category="excel",
        report_day=report_day,
    )

    troubleshooting_onedrive_path = upload_file_to_onedrive(
        source_path=reports["troubleshooting"],
        category="troubleshooting",
        report_day=report_day,
    )

    return {
        "low_psh_generation": str(low_psh_generation_onedrive_path),
        "alarms": str(alarms_onedrive_path),
        "troubleshooting": str(troubleshooting_onedrive_path),
    }

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)

        report_day = today_gmt8()
        reports = find_required_daily_reports()

        onedrive_paths = upload_required_reports_to_onedrive(reports)

        subject = (
            "Service Performance Monitoring System Daily Reports "
            f"({format_date_ddmmyyyy(report_day)})"
        )

        body = (
            "Dear TERA Service Team,\n\n"
            "Attached are the Service Performance Monitoring System daily reports "
            f"for {format_date_ddmmyyyy(report_day)}.\n\n"
            "Attached Report Files:\n"
            f"1. {reports['low_psh_generation'].name}\n"
            f"2. {reports['alarms'].name}\n"
            f"3. {reports['troubleshooting'].name}\n\n"
            "OneDrive Upload Directories:\n"
            f"1. {onedrive_paths['low_psh_generation']}\n"
            f"2. {onedrive_paths['alarms']}\n"
            f"3. {onedrive_paths['troubleshooting']}\n\n"
            "(This email is generated automatically. Please do not reply.)"
        )

        send_email_with_attachments(
            subject=subject,
            body=body,
            attachment_paths=[
                reports["low_psh_generation"],
                reports["alarms"],
                reports["troubleshooting"],
            ],
        )

        message = (
            "Daily reports uploaded to OneDrive and emailed successfully.\n"
            "Uploaded and attached files:\n"
            f"1. {reports['low_psh_generation'].name}\n"
            f"2. {reports['alarms'].name}\n"
            f"3. {reports['troubleshooting'].name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "report_day": str(report_day),
                "uploaded_and_attached_files": [
                    reports["low_psh_generation"].name,
                    reports["alarms"].name,
                    reports["troubleshooting"].name,
                ],
                "local_paths": {
                    "low_psh_generation": str(reports["low_psh_generation"]).replace("\\", "/"),
                    "alarms": str(reports["alarms"]).replace("\\", "/"),
                    "troubleshooting": str(reports["troubleshooting"]).replace("\\", "/"),
                },
                "onedrive_paths": onedrive_paths,
            },
        )

        print(message)

    except Exception as exc:
        db.rollback()

        if run_id is not None:
            finish_run(db, run_id, "fail", str(exc))

        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()