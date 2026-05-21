from __future__ import annotations
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from app.db.session import SessionLocal
from app.services.activity_log_service import log_activity

def _normalise_report_day(value) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return datetime.strptime(value, "%Y-%m-%d").date()

    raise ValueError(f"Unsupported report_day value: {value!r}")

def _get_versioned_destination(dest_dir: Path, filename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    original = Path(filename)
    stem = original.stem
    suffix = original.suffix

    candidate = dest_dir / original.name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        versioned = dest_dir / f"{stem} ({counter}){suffix}"
        if not versioned.exists():
            return versioned
        counter += 1

def get_onedrive_root_dir() -> Path:
    root = os.getenv("ONEDRIVE_REPORT_DIR", "").strip()

    if not root:
        raise RuntimeError("ONEDRIVE_REPORT_DIR is not set in .env")

    return Path(root)

def get_onedrive_monthly_dir() -> Path:
    folder_name = os.getenv("ONEDRIVE_MONTHLY_DIR", "monthly").strip() or "monthly"
    return get_onedrive_root_dir() / folder_name

def get_onedrive_troubleshooting_dir() -> Path:
    folder_name = (
        os.getenv("ONEDRIVE_TROUBLESHOOTING_DIR", "Troubleshooting").strip()
        or "Troubleshooting"
    )
    return get_onedrive_root_dir() / folder_name

def get_onedrive_excel_dir() -> Path:
    folder_name = os.getenv("ONEDRIVE_EXCEL_DIR", "Excel").strip() or "Excel"
    return get_onedrive_root_dir() / folder_name

def _log_onedrive_activity(
    *,
    action: str,
    status_code: int,
    source_path: str | Path | None,
    dest_path: str | Path | None,
    category: str | None,
    report_day=None,
    error: str | None = None,
) -> None:
    db = SessionLocal()

    try:
        dest_name = Path(dest_path).name if dest_path else None

        log_activity(
            db,
            event_type="System event",
            user_type="system",
            user_name=None,
            action=action,
            target=dest_name,
            path="onedrive_service",
            method="COPY",
            status_code=status_code,
            details={
                "source_path": str(source_path).replace("\\", "/") if source_path else None,
                "dest_path": str(dest_path).replace("\\", "/") if dest_path else None,
                "onedrive_path": str(dest_path).replace("\\", "/") if dest_path else None,
                "category": category,
                "report_day": str(report_day) if report_day else None,
                "error": error,
            },
        )

        db.commit()

    except Exception:
        db.rollback()

    finally:
        db.close()

def upload_file_to_onedrive(
    source_path: str | Path,
    category: str,
    report_day=None,
    *,
    use_year_month_subfolders: bool = True,
) -> Path:
    source = Path(source_path)

    if not source.exists() or not source.is_file():
        error = f"Source file not found: {source}"

        _log_onedrive_activity(
            action="OneDrive upload failed",
            status_code=404,
            source_path=source,
            dest_path=None,
            category=category,
            report_day=report_day,
            error=error,
        )

        raise FileNotFoundError(error)

    category = category.lower().strip()

    if category == "monthly":
        dest_dir = get_onedrive_monthly_dir()
    elif category == "troubleshooting":
        dest_dir = get_onedrive_troubleshooting_dir()
    elif category == "excel":
        dest_dir = get_onedrive_excel_dir()
    else:
        error = f"Unsupported OneDrive upload category: {category}"

        _log_onedrive_activity(
            action="OneDrive upload failed",
            status_code=400,
            source_path=source,
            dest_path=None,
            category=category,
            report_day=report_day,
            error=error,
        )

        raise ValueError(error)

    if report_day is not None and use_year_month_subfolders:
        d = _normalise_report_day(report_day)
        dest_dir = dest_dir / f"{d.year}" / f"{d.month:02d}"

    dest_path = _get_versioned_destination(dest_dir, source.name)

    try:
        shutil.copy2(source, dest_path)

        _log_onedrive_activity(
            action="OneDrive upload",
            status_code=200,
            source_path=source,
            dest_path=dest_path,
            category=category,
            report_day=report_day,
        )

        return dest_path

    except Exception as e:
        _log_onedrive_activity(
            action="OneDrive upload failed",
            status_code=500,
            source_path=source,
            dest_path=dest_path,
            category=category,
            report_day=report_day,
            error=str(e),
        )

        raise