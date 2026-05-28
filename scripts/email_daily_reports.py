from __future__ import annotations
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.email_service import send_email_with_attachments
from app.services.onedrive_service import upload_file_to_onedrive
from app.services.report_file_storage_service import (
    find_report_file_for_day,
    materialise_report_file_from_db,
    store_report_file_in_db,
    update_report_file_onedrive_backup,
)
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
    report_types: list[str]

REPORT_REQUIREMENTS = [
    DailyReportRequirement(
        key="low_psh_generation",
        display_name="low_psh_generation_report",
        directory=EXCEL_OVERALL_DIR,
        prefix="low_psh_generation_report_",
        suffix=".xlsx",
        onedrive_category="excel",
        report_types=["LOW_PSH_GENERATION_XLSX"],
    ),
    DailyReportRequirement(
        key="alarms",
        display_name="alarms_report",
        directory=EXCEL_ALARMS_DIR,
        prefix="alarms_report_",
        suffix=".xlsx",
        onedrive_category="excel",
        report_types=["ALARMS_XLSX", "ALARM_XLSX"],
    ),
    DailyReportRequirement(
        key="troubleshooting",
        display_name="troubleshooting_report",
        directory=TROUBLESHOOTING_REPORTS_DIR,
        prefix="troubleshooting_report_",
        suffix=".pdf",
        onedrive_category="troubleshooting",
        report_types=["TROUBLESHOOTING_PDF"],
    ),
]

def _find_local_report_file_for_exact_day(
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

def find_daily_reports_for_previous_day(db) -> tuple[dict[str, dict], list[str], object]:
    ensure_report_directories()

    report_day = today_gmt8() - timedelta(days=1)
    report_day_text = report_day.strftime("%d-%m-%Y")

    found_reports: dict[str, dict] = {}
    notes: list[str] = []

    for requirement in REPORT_REQUIREMENTS:
        report_record = find_report_file_for_day(
            db,
            report_types=requirement.report_types,
            report_day=report_day,
            file_prefix=requirement.prefix,
            file_suffix=requirement.suffix,
        )

        if report_record is not None:
            found_reports[requirement.key] = {
                "source": "database",
                "record": report_record,
                "file_name": report_record["file_name"],
            }
            continue

        local_file = _find_local_report_file_for_exact_day(
            requirement,
            report_day_text=report_day_text,
        )

        if local_file is not None:
            report_file_id = store_report_file_in_db(
                db,
                report_type=requirement.report_types[0],
                report_day=report_day,
                file_path=local_file,
                local_file_path=local_file,
            )
            db.commit()

            found_reports[requirement.key] = {
                "source": "local_imported_to_database",
                "record": {
                    "id": report_file_id,
                    "file_name": local_file.name,
                    "local_file_path": str(local_file).replace("\\", "/"),
                },
                "file_name": local_file.name,
            }
            continue

        notes.append(
            f"No {requirement.display_name} was generated for {report_day_text}."
        )

    return found_reports, notes, report_day

def materialise_available_reports(
    db,
    reports: dict[str, dict],
    *,
    temp_dir: Path,
) -> dict[str, Path]:
    materialised_paths: dict[str, Path] = {}

    for key, item in reports.items():
        record = item["record"]
        report_file_id = record.get("id")

        if report_file_id is None:
            continue

        materialised_paths[key] = materialise_report_file_from_db(
            db,
            report_file_id=int(report_file_id),
            output_dir=temp_dir,
        )

    return materialised_paths

def upload_available_reports_to_onedrive(
    db,
    reports: dict[str, dict],
    materialised_paths: dict[str, Path],
    *,
    report_day,
) -> dict[str, str]:
    onedrive_paths: dict[str, str] = {}

    for requirement in REPORT_REQUIREMENTS:
        report_path = materialised_paths.get(requirement.key)

        if report_path is None:
            continue

        onedrive_path = upload_file_to_onedrive(
            source_path=report_path,
            category=requirement.onedrive_category,
            report_day=report_day,
        )

        onedrive_paths[requirement.key] = str(onedrive_path)

        record = reports.get(requirement.key, {}).get("record") or {}
        report_file_id = record.get("id")

        if report_file_id is not None:
            update_report_file_onedrive_backup(
                db,
                report_file_id=int(report_file_id),
                onedrive_path=onedrive_path,
            )
            db.commit()

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
    reports: dict[str, dict],
    onedrive_paths: dict[str, str],
    notes: list[str],
) -> str:
    report_day_text = format_date_ddmmyyyy(report_day)

    attached_file_names: list[str] = []
    uploaded_paths: list[str] = []

    for requirement in REPORT_REQUIREMENTS:
        report_item = reports.get(requirement.key)

        if report_item is not None:
            attached_file_names.append(report_item["file_name"])

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

        reports, notes, report_day = find_daily_reports_for_previous_day(db)

        with tempfile.TemporaryDirectory(prefix="tera_spms_daily_email_") as tmp:
            temp_dir = Path(tmp)

            materialised_paths = materialise_available_reports(
                db,
                reports,
                temp_dir=temp_dir,
            )

            onedrive_paths = upload_available_reports_to_onedrive(
                db,
                reports,
                materialised_paths,
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
                materialised_paths[requirement.key]
                for requirement in REPORT_REQUIREMENTS
                if requirement.key in materialised_paths
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
                "report_file_ids": {
                    key: item.get("record", {}).get("id")
                    for key, item in reports.items()
                },
                "onedrive_paths": onedrive_paths,
                "primary_storage": "TigerData",
                "backup_storage": "OneDrive",
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