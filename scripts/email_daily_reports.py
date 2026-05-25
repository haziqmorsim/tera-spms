from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
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

@dataclass(slots=True)
class DailyReportRequirement:
    key: str
    display_name: str
    directory: Path
    prefix: str
    suffix: str
    onedrive_category: str

REPORT_REQUIREMENTS = [
    DailyReportRequirement(
        key="low_psh_generation",
        display_name="low_psh_generation_report",
        directory=EXCEL_OVERALL_DIR,
        prefix="low_psh_generation_report_",
        suffix=".xlsx",
        onedrive_category="excel",
    ),
    DailyReportRequirement(
        key="alarms",
        display_name="alarms_report",
        directory=EXCEL_ALARMS_DIR,
        prefix="alarms_report_",
        suffix=".xlsx",
        onedrive_category="excel",
    ),
    DailyReportRequirement(
        key="troubleshooting",
        display_name="troubleshooting_report",
        directory=TROUBLESHOOTING_REPORTS_DIR,
        prefix="troubleshooting_report_",
        suffix=".pdf",
        onedrive_category="troubleshooting",
    ),
]

def _find_report_file_for_exact_day(
    requirement: DailyReportRequirement,
    *,
    report_day_text: str,
) -> Path | None:
    directory = requirement.directory

    if not directory.exists():
        return None

    matches = [
        file
        for file in directory.iterdir()
        if file.is_file()
        and file.name.lower().startswith(requirement.prefix.lower())
        and file.suffix.lower() == requirement.suffix.lower()
        and report_day_text in file.name
    ]

    if not matches:
        return None

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]

def find_daily_reports_for_previous_day() -> tuple[dict[str, Path], list[str], object]:

    ensure_report_directories()

    report_day = today_gmt8() - timedelta(days=1)
    report_day_text = report_day.strftime("%d-%m-%Y")

    found_reports: dict[str, Path] = {}
    notes: list[str] = []

    for requirement in REPORT_REQUIREMENTS:
        report_file = _find_report_file_for_exact_day(
            requirement,
            report_day_text=report_day_text,
        )

        if report_file is None:
            notes.append(
                f"No {requirement.display_name} was generated for {report_day_text}."
            )
            continue

        found_reports[requirement.key] = report_file

    return found_reports, notes, report_day

def upload_available_reports_to_onedrive(
    reports: dict[str, Path],
    *,
    report_day,
) -> dict[str, str]:
    onedrive_paths: dict[str, str] = {}

    for requirement in REPORT_REQUIREMENTS:
        report_file = reports.get(requirement.key)

        if report_file is None:
            continue

        onedrive_path = upload_file_to_onedrive(
            source_path=report_file,
            category=requirement.onedrive_category,
            report_day=report_day,
        )

        onedrive_paths[requirement.key] = str(onedrive_path)

    return onedrive_paths

def _build_numbered_lines(values: list[str]) -> str:
    if not values:
        return ""

    return "\n".join(
        f"{index}. {value}"
        for index, value in enumerate(values, start=1)
    )

def build_daily_email_body(
    *,
    report_day,
    reports: dict[str, Path],
    onedrive_paths: dict[str, str],
    notes: list[str],
) -> str:
    report_day_text = format_date_ddmmyyyy(report_day)

    attached_file_names: list[str] = []
    uploaded_paths: list[str] = []

    for requirement in REPORT_REQUIREMENTS:
        report_file = reports.get(requirement.key)

        if report_file is not None:
            attached_file_names.append(report_file.name)

        onedrive_path = onedrive_paths.get(requirement.key)

        if onedrive_path:
            uploaded_paths.append(onedrive_path)

    if attached_file_names:
        attached_files_section = _build_numbered_lines(attached_file_names)
    else:
        attached_files_section = "No report files were attached."

    if uploaded_paths:
        onedrive_section = _build_numbered_lines(uploaded_paths)
    else:
        onedrive_section = "No report files were uploaded to OneDrive."

    if notes:
        notes_section = "\n\nNotes:\n" + _build_numbered_lines(notes)
    else:
        notes_section = ""

    return (
        "Dear TERA Service Team,\n\n"
        "Attached are the Service Performance Monitoring System daily reports "
        f"for {report_day_text}.\n\n"
        "Attached Report Files:\n"
        f"{attached_files_section}\n\n"
        "OneDrive Upload Directories:\n"
        f"{onedrive_section}"
        f"{notes_section}\n\n"
        "(This email is generated automatically. Please do not reply.)"
    )

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)

        reports, notes, report_day = find_daily_reports_for_previous_day()
        onedrive_paths = upload_available_reports_to_onedrive(
            reports,
            report_day=report_day,
        )

        subject = (
            "Service Performance Monitoring System Daily Reports "
            f"({format_date_ddmmyyyy(report_day)})"
        )

        body = build_daily_email_body(
            report_day=report_day,
            reports=reports,
            onedrive_paths=onedrive_paths,
            notes=notes,
        )

        attachment_paths = [
            reports[requirement.key]
            for requirement in REPORT_REQUIREMENTS
            if requirement.key in reports
        ]

        send_email_with_attachments(
            subject=subject,
            body=body,
            attachment_paths=attachment_paths,
        )

        attached_file_names = [path.name for path in attachment_paths]

        if attached_file_names:
            attached_text = "\n".join(
                f"{index}. {name}"
                for index, name in enumerate(attached_file_names, start=1)
            )
        else:
            attached_text = "No report files were attached."

        if notes:
            notes_text = "\n".join(f"- {note}" for note in notes)
        else:
            notes_text = "No missing reports."

        message = (
            "Daily reports email processed successfully.\n"
            f"Report day: {format_date_ddmmyyyy(report_day)}\n"
            "Uploaded and attached files:\n"
            f"{attached_text}\n"
            "Notes:\n"
            f"{notes_text}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "report_day": str(report_day),
                "attached_files": attached_file_names,
                "missing_report_notes": notes,
                "local_paths": {
                    key: str(path).replace("\\", "/")
                    for key, path in reports.items()
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