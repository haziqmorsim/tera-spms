from __future__ import annotations
import calendar
import re
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.report_file_storage_service import (
    ensure_report_files_table,
    store_report_file_in_db,
)

load_dotenv()

REPORTS_ROOT = Path("reports")
DAILY_DATE_PATTERN = re.compile(r"(\d{2}-\d{2}-\d{4})")
MONTHLY_DATE_PATTERN = re.compile(r"monthly_report_(\d{2})-(\d{4})", re.IGNORECASE)
REPORT_TYPE_RULES = [
    {
        "prefix": "alarms_report_",
        "suffix": ".xlsx",
        "report_type": "ALARMS_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "alarm_report_",
        "suffix": ".xlsx",
        "report_type": "ALARMS_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "low_psh_plants_report_",
        "suffix": ".xlsx",
        "report_type": "LOW_PSH_PLANTS_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "low_performing_inverters_report_",
        "suffix": ".xlsx",
        "report_type": "LOW_PERFORMING_INVERTERS_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "low_performing_strings_report_",
        "suffix": ".xlsx",
        "report_type": "LOW_PERFORMING_STRINGS_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "low_psh_generation_report_",
        "suffix": ".xlsx",
        "report_type": "LOW_PSH_GENERATION_XLSX",
        "date_type": "daily",
    },
    {
        "prefix": "troubleshooting_report_",
        "suffix": ".pdf",
        "report_type": "TROUBLESHOOTING_PDF",
        "date_type": "daily",
    },
    {
        "prefix": "monthly_report_",
        "suffix": ".pdf",
        "report_type": "MONTHLY_PDF",
        "date_type": "monthly",
    },
    {
        "prefix": "monthly_report_",
        "suffix": ".xlsx",
        "report_type": "MONTHLY_XLSX",
        "date_type": "monthly",
    },
]

def _detect_rule(file_path: Path) -> dict | None:
    file_name = file_path.name.lower()

    for rule in REPORT_TYPE_RULES:
        if file_name.startswith(rule["prefix"]) and file_name.endswith(rule["suffix"]):
            return rule

    return None

def _extract_daily_report_day(file_name: str) -> date | None:
    match = DAILY_DATE_PATTERN.search(file_name)

    if not match:
        return None

    return datetime.strptime(match.group(1), "%d-%m-%Y").date()

def _extract_monthly_report_day(file_name: str) -> date | None:
    match = MONTHLY_DATE_PATTERN.search(file_name)

    if not match:
        return None

    month = int(match.group(1))
    year = int(match.group(2))

    if month < 1 or month > 12:
        return None

    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)

def _extract_report_day(file_path: Path, rule: dict) -> date | None:
    date_type = rule.get("date_type")

    if date_type == "monthly":
        return _extract_monthly_report_day(file_path.name)

    return _extract_daily_report_day(file_path.name)

def _find_report_files() -> list[Path]:
    if not REPORTS_ROOT.exists():
        raise FileNotFoundError(f"Reports folder does not exist: {REPORTS_ROOT}")

    files: list[Path] = []

    for file_path in REPORTS_ROOT.rglob("*"):
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() not in {".xlsx", ".pdf"}:
            continue

        rule = _detect_rule(file_path)

        if rule is None:
            continue

        files.append(file_path)

    files.sort(key=lambda path: str(path).lower())
    return files

def main() -> None:
    db = SessionLocal()

    inserted_or_updated = 0
    skipped = 0
    failed = 0

    try:
        ensure_report_files_table(db)
        db.commit()

        report_files = _find_report_files()

        print(f"Found report files: {len(report_files)}")

        for file_path in report_files:
            rule = _detect_rule(file_path)

            if rule is None:
                print(f"Skipped unsupported file: {file_path}")
                skipped += 1
                continue

            report_type = rule["report_type"]
            report_day = _extract_report_day(file_path, rule)

            if report_day is None:
                print(f"Skipped file with unsupported date format: {file_path}")
                skipped += 1
                continue

            try:
                report_file_id = store_report_file_in_db(
                    db,
                    report_type=report_type,
                    report_day=report_day,
                    file_path=file_path,
                    local_file_path=file_path,
                )

                db.commit()

                print(
                    f"Stored report_file_id={report_file_id} | "
                    f"{report_type} | {report_day} | {file_path}"
                )

                inserted_or_updated += 1

            except Exception as exc:
                db.rollback()
                failed += 1
                print(f"Failed to store {file_path}: {exc}")

        print()
        print("Backfill completed.")
        print(f"Inserted/updated: {inserted_or_updated}")
        print(f"Skipped: {skipped}")
        print(f"Failed: {failed}")

    finally:
        db.close()

if __name__ == "__main__":
    main()