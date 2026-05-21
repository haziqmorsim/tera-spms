from __future__ import annotations
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.activity_log_service import log_activity, resolve_user_name_from_request
from app.services.monthly_xlsx_report_service import build_monthly_xlsx_report
from app.services.onedrive_service import upload_file_to_onedrive
from app.services.report_storage_service import save_generated_report
from app.services.tnb_bill_parser import parse_tnb_bill_pdf
from app.utils.time_utils import APP_TZ, format_date_ddmmyyyy, format_datetime_gmt8

router = APIRouter(prefix="/reports", tags=["reports"])

REPORTS_DIR = Path("reports")
MONTHLY_DIR = REPORTS_DIR / "monthly"
UPLOADS_DIR = Path("data") / "tnb" / "uploads"

def _get_setting(db: Session, key: str, default: str = "") -> str:
    try:
        row = (
            db.execute(
                text(
                    """
                    SELECT setting_value
                    FROM app_settings
                    WHERE setting_key = :key
                    LIMIT 1
                    """
                ),
                {"key": key},
            )
            .mappings()
            .first()
        )

        if not row:
            return default

        return row["setting_value"] or default

    except Exception:
        db.rollback()
        return default

def _get_onedrive_report_root(db: Session) -> Path | None:
    configured = _get_setting(
        db,
        "onedrive_report_dir",
        os.getenv("ONEDRIVE_REPORT_DIR", ""),
    ).strip()

    if not configured:
        return None

    return Path(configured).expanduser().resolve()

def _safe_report_path(relative_path: str) -> Path:
    candidate = (REPORTS_DIR / relative_path).resolve()
    reports_root = REPORTS_DIR.resolve()

    if not str(candidate).startswith(str(reports_root)):
        raise HTTPException(status_code=400, detail="Invalid report path.")

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Report file not found.")

    return candidate

def _safe_onedrive_report_path(db: Session, relative_path: str) -> Path:
    onedrive_root = _get_onedrive_report_root(db)

    if onedrive_root is None:
        raise HTTPException(
            status_code=400,
            detail="OneDrive Report Directory is not configured.",
        )

    candidate = (onedrive_root / relative_path).resolve()

    if not str(candidate).startswith(str(onedrive_root)):
        raise HTTPException(status_code=400, detail="Invalid OneDrive report path.")

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="OneDrive report file not found.")

    return candidate

def to_report_url(file_path: str | None) -> str | None:
    if not file_path:
        return None

    normalized = file_path.replace("\\", "/").strip()

    if normalized.startswith("reports/"):
        relative = normalized[len("reports/") :]
    else:
        relative = normalized

    return f"/api/reports/open/{quote(relative)}"

def to_onedrive_report_url(
    file_path: str | Path | None,
    *,
    onedrive_root: Path | None,
) -> str | None:
    if not file_path or onedrive_root is None:
        return None

    try:
        path = Path(file_path).expanduser().resolve()
        relative = path.relative_to(onedrive_root)
        return f"/api/reports/onedrive/open/{quote(relative.as_posix())}"

    except Exception:
        return None

def _is_http_url(value: str | None) -> bool:
    if not value:
        return False

    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")

def _file_item_from_onedrive(
    file: Path,
    *,
    onedrive_root: Path,
) -> dict:
    modified_dt = datetime.fromtimestamp(file.stat().st_mtime, APP_TZ)

    return {
        "file_name": file.name,
        "file_path": file.as_posix(),
        "file_url": to_onedrive_report_url(file, onedrive_root=onedrive_root),
        "onedrive_path": file.as_posix(),
        "modified_at": format_datetime_gmt8(modified_dt),
        "generated_at": format_datetime_gmt8(modified_dt),
        "_modified_at_raw": modified_dt,
    }

def _scan_onedrive_report_files(db: Session) -> tuple[list[dict], list[dict], list[dict], str | None]:
    onedrive_root = _get_onedrive_report_root(db)

    if onedrive_root is None:
        return [], [], [], "OneDrive Report Directory is not configured."

    if not onedrive_root.exists() or not onedrive_root.is_dir():
        return [], [], [], f"OneDrive Report Directory does not exist: {onedrive_root}"

    monthly_reports: list[dict] = []
    troubleshooting_reports: list[dict] = []
    spreadsheet_reports: list[dict] = []

    for file in onedrive_root.rglob("*"):
        if not file.is_file():
            continue

        lower_name = file.name.lower()
        suffix = file.suffix.lower()
        parts = {part.lower() for part in file.relative_to(onedrive_root).parts}

        item = _file_item_from_onedrive(file, onedrive_root=onedrive_root)

        is_monthly = (
            lower_name.startswith("monthly_report_")
            and suffix in {".pdf", ".xlsx"}
            and ("monthly" in parts or "monthly reports" in " ".join(parts))
        )

        is_troubleshooting = (
            suffix == ".pdf"
            and (
                lower_name.startswith("troubleshooting_report_")
                or "troubleshooting" in parts
            )
        )

        is_alarm_excel = (
            suffix == ".xlsx"
            and (
                lower_name.startswith("alarms_report_")
                or lower_name.startswith("alarm_report_")
                or "alarms" in parts
            )
        )

        is_low_psh_generation_excel = (
            suffix == ".xlsx"
            and (
                lower_name.startswith("low_psh_generation_report_")
                or "overall" in parts
            )
        )

        if is_monthly:
            monthly_reports.append(item)

        elif is_troubleshooting:
            troubleshooting_reports.append(item)

        elif is_alarm_excel or is_low_psh_generation_excel:
            spreadsheet_reports.append(item)

    monthly_reports.sort(key=lambda x: x["_modified_at_raw"], reverse=True)
    troubleshooting_reports.sort(key=lambda x: x["_modified_at_raw"], reverse=True)
    spreadsheet_reports.sort(key=lambda x: x["_modified_at_raw"], reverse=True)

    for group in (monthly_reports, troubleshooting_reports, spreadsheet_reports):
        for item in group:
            item.pop("_modified_at_raw", None)

    return monthly_reports, troubleshooting_reports, spreadsheet_reports, None

@router.get("/open/{file_path:path}")
def open_report_file(
    file_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    report_file = _safe_report_path(file_path)
    user_name = resolve_user_name_from_request(request)

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user" if user_name else "system",
            user_name=user_name,
            action="Open report",
            target=report_file.name,
            path=f"/api/reports/open/{file_path}",
            method="GET",
            status_code=200,
            details={
                "file_name": report_file.name,
                "file_path": str(report_file).replace("\\", "/"),
            },
        )
    except Exception:
        db.rollback()

    return FileResponse(
        path=str(report_file),
        filename=report_file.name,
    )

@router.get("/onedrive/open/{file_path:path}")
def open_onedrive_report_file(
    file_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    report_file = _safe_onedrive_report_path(db, file_path)
    user_name = resolve_user_name_from_request(request)

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user" if user_name else "system",
            user_name=user_name,
            action="Open OneDrive report",
            target=report_file.name,
            path=f"/api/reports/onedrive/open/{file_path}",
            method="GET",
            status_code=200,
            details={
                "file_name": report_file.name,
                "onedrive_path": str(report_file).replace("\\", "/"),
            },
        )
    except Exception:
        db.rollback()

    return FileResponse(
        path=str(report_file),
        filename=report_file.name,
    )

@router.post("/monthly/generate-from-bill")
async def generate_monthly_report_from_bill(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file name received.")

    suffix = Path(file.filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF electricity bill files are supported.",
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(APP_TZ).strftime("%Y%m%d_%H%M%S")
    upload_path = UPLOADS_DIR / f"{timestamp}_{Path(file.filename).name}"
    user_name = resolve_user_name_from_request(request)

    try:
        with upload_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        parsed = parse_tnb_bill_pdf(upload_path)

        if not any(
            [
                parsed.company_name,
                parsed.account_no,
                parsed.total_bill_rm,
                parsed.total_usage_kwh,
                parsed.bill_date,
                parsed.period_end,
            ]
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "The uploaded bill could not be parsed. "
                    "Make sure Tesseract OCR is installed and TESSERACT_CMD is configured."
                ),
            )

        output_path = build_monthly_xlsx_report(parsed, output_dir=MONTHLY_DIR)
        report_day = parsed.period_end or datetime.now(APP_TZ).date()

        onedrive_path = upload_file_to_onedrive(
            source_path=output_path,
            category="monthly",
            report_day=report_day,
            use_year_month_subfolders=True,
        )

        onedrive_root = _get_onedrive_report_root(db)
        onedrive_file_url = to_onedrive_report_url(
            onedrive_path,
            onedrive_root=onedrive_root,
        )

        save_generated_report(
            report_type="MONTHLY_XLSX",
            file_path=str(onedrive_path).replace("\\", "/"),
            local_file_path=str(output_path).replace("\\", "/"),
            report_day=report_day,
        )

        try:
            log_activity(
                db,
                event_type="User action",
                user_type="user" if user_name else "system",
                user_name=user_name,
                action="Generate monthly report",
                target=output_path.name,
                path="/api/reports/monthly/generate-from-bill",
                method="POST",
                status_code=200,
                details={
                    "source_file": file.filename,
                    "generated_file": output_path.name,
                    "local_file_path": str(output_path).replace("\\", "/"),
                    "onedrive_path": str(onedrive_path).replace("\\", "/"),
                    "company_name": parsed.company_name,
                    "account_no": parsed.account_no,
                    "period_start": format_date_ddmmyyyy(parsed.period_start)
                    if parsed.period_start
                    else None,
                    "period_end": format_date_ddmmyyyy(parsed.period_end)
                    if parsed.period_end
                    else None,
                },
            )
        except Exception:
            db.rollback()

        return {
            "message": "Monthly report generated and uploaded to OneDrive successfully.",
            "file_name": output_path.name,
            "file_path": str(onedrive_path).replace("\\", "/"),
            "file_url": onedrive_file_url,
            "onedrive_path": str(onedrive_path).replace("\\", "/"),
            "report_day": format_date_ddmmyyyy(report_day),
            "parsed": {
                "company_name": parsed.company_name,
                "account_no": parsed.account_no,
                "period_start": format_date_ddmmyyyy(parsed.period_start)
                if parsed.period_start
                else None,
                "period_end": format_date_ddmmyyyy(parsed.period_end)
                if parsed.period_end
                else None,
                "total_bill_rm": parsed.total_bill_rm,
                "total_usage_kwh": parsed.total_usage_kwh,
            },
        }

    except HTTPException as e:
        try:
            log_activity(
                db,
                event_type="System event",
                user_type="user" if user_name else "system",
                user_name=user_name,
                action="Generate monthly report failed",
                target=file.filename,
                path="/api/reports/monthly/generate-from-bill",
                method="POST",
                status_code=e.status_code,
                details={"error": str(e.detail)},
            )
        except Exception:
            db.rollback()

        raise

    except Exception as e:
        try:
            db.rollback()
            log_activity(
                db,
                event_type="System event",
                user_type="user" if user_name else "system",
                user_name=user_name,
                action="Generate monthly report failed",
                target=file.filename,
                path="/api/reports/monthly/generate-from-bill",
                method="POST",
                status_code=500,
                details={"error": str(e)},
            )
        except Exception:
            db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate monthly report: {e}",
        ) from e

    finally:
        await file.close()

@router.get("/overview")
def reports_overview(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    report_type,
                    report_day,
                    file_path,
                    status,
                    notes,
                    generated_at
                FROM generated_reports
                ORDER BY generated_at DESC NULLS LAST, report_day DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )

    onedrive_root = _get_onedrive_report_root(db)

    generated_reports = [
        {
            "report_type": r["report_type"],
            "report_day": (
                format_date_ddmmyyyy(r["report_day"]) if r["report_day"] else None
            ),
            "file_path": r["file_path"],
            "file_url": to_onedrive_report_url(
                r["file_path"],
                onedrive_root=onedrive_root,
            )
            if r["file_path"]
            else None,
            "status": r["status"],
            "notes": r["notes"],
            "generated_at": (
                format_datetime_gmt8(r["generated_at"]) if r["generated_at"] else None
            ),
        }
        for r in rows
    ]

    monthly_reports, troubleshooting_reports, csv_reports, onedrive_warning = (
        _scan_onedrive_report_files(db)
    )

    total_files_count = (
        len(monthly_reports) + len(troubleshooting_reports) + len(csv_reports)
    )

    summary = {
        "generated_reports_count": total_files_count,
        "monthly_reports_count": len(monthly_reports),
        "troubleshooting_reports_count": len(troubleshooting_reports),
        "csv_reports_count": len(csv_reports),
        "logged_generated_reports_count": len(generated_reports),
        "onedrive_report_dir": str(onedrive_root) if onedrive_root else None,
        "onedrive_warning": onedrive_warning,
    }

    return {
        "summary": summary,
        "generated_reports": generated_reports,
        "monthly_reports": monthly_reports[:limit],
        "troubleshooting_reports": troubleshooting_reports[:limit],
        "csv_reports": csv_reports[:limit],
    }