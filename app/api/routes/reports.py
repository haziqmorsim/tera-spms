from __future__ import annotations
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.activity_log_service import log_activity, resolve_user_name_from_request
from app.services.monthly_xlsx_report_service import build_monthly_xlsx_report
from app.services.onedrive_service import upload_file_to_onedrive
from app.services.report_file_storage_service import (
    fetch_report_file_items,
    get_report_file_for_download,
    update_report_file_onedrive_backup_by_local_file,
)
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

def _format_report_day(value) -> str | None:
    if not value:
        return None

    return format_date_ddmmyyyy(value)

def _format_report_datetime(value) -> str | None:
    if not value:
        return None

    return format_datetime_gmt8(value)

def _report_file_item(row: dict) -> dict:
    file_url = row.get("file_url")

    if not file_url and row.get("id"):
        file_url = f"/api/reports/files/{row['id']}/download"

    return {
        "id": row.get("id"),
        "report_type": row.get("report_type"),
        "report_day": _format_report_day(row.get("report_day")),
        "file_name": row.get("file_name"),
        "file_path": row.get("file_path"),
        "file_url": file_url,
        "download_url": file_url,
        "local_file_path": row.get("local_file_path"),
        "onedrive_path": row.get("onedrive_path"),
        "onedrive_web_url": row.get("onedrive_web_url"),
        "file_size_bytes": row.get("file_size_bytes"),
        "generated_at": _format_report_datetime(row.get("updated_at") or row.get("created_at")),
        "modified_at": _format_report_datetime(row.get("updated_at") or row.get("created_at")),
    }

def _categorise_report_files(report_files: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    monthly_reports: list[dict] = []
    troubleshooting_reports: list[dict] = []
    spreadsheet_reports: list[dict] = []

    for row in report_files:
        item = _report_file_item(row)

        report_type = str(row.get("report_type") or "").upper()
        file_name = str(row.get("file_name") or "").lower()
        file_ext = str(row.get("file_ext") or Path(file_name).suffix).lower()

        is_monthly = (
            report_type in {"MONTHLY_XLSX", "MONTHLY_PDF"}
            or file_name.startswith("monthly_report_")
        )

        is_troubleshooting = (
            report_type == "TROUBLESHOOTING_PDF"
            or file_name.startswith("troubleshooting_report_")
        )

        is_spreadsheet = (
            file_ext == ".xlsx"
            and (
                report_type in {
                    "ALARMS_XLSX",
                    "ALARM_XLSX",
                    "LOW_PSH_GENERATION_XLSX",
                }
                or file_name.startswith("alarms_report_")
                or file_name.startswith("alarm_report_")
                or file_name.startswith("low_psh_generation_report_")
            )
        )

        if is_monthly:
            monthly_reports.append(item)

        elif is_troubleshooting:
            troubleshooting_reports.append(item)

        elif is_spreadsheet:
            spreadsheet_reports.append(item)

    return monthly_reports, troubleshooting_reports, spreadsheet_reports

@router.get("/files/{report_file_id}/download")
def download_report_file_from_db(
    report_file_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    row = get_report_file_for_download(db, report_file_id=report_file_id)

    if not row:
        raise HTTPException(status_code=404, detail="Report file not found.")

    user_name = resolve_user_name_from_request(request)

    try:
        log_activity(
            db,
            event_type="User action",
            user_type="user" if user_name else "system",
            user_name=user_name,
            action="Download report from TigerData",
            target=row["file_name"],
            path=f"/api/reports/files/{report_file_id}/download",
            method="GET",
            status_code=200,
            details={
                "report_file_id": report_file_id,
                "file_name": row["file_name"],
                "report_type": row["report_type"],
            },
        )
    except Exception:
        db.rollback()

    return Response(
        content=bytes(row["file_data"]),
        media_type=row["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{row["file_name"]}"'
        },
    )

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
            onedrive_path=str(onedrive_path).replace("\\", "/"),
            report_day=report_day,
        )

        try:
            update_report_file_onedrive_backup_by_local_file(
                db,
                local_file_path=output_path,
                onedrive_path=onedrive_path,
            )
            db.commit()
        except Exception:
            db.rollback()

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
            "message": "Monthly report generated, stored in TigerData, and uploaded to OneDrive successfully.",
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
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    report_files = fetch_report_file_items(db, limit=limit * 5)

    monthly_reports, troubleshooting_reports, csv_reports = _categorise_report_files(
        report_files
    )

    generated_rows = (
        db.execute(
            text(
                """
                SELECT
                    gr.report_type,
                    gr.report_day,
                    gr.file_path,
                    gr.local_file_path,
                    gr.report_file_id,
                    gr.status,
                    gr.notes,
                    gr.generated_at,
                    rf.file_name,
                    rf.onedrive_path,
                    rf.onedrive_web_url
                FROM generated_reports gr
                LEFT JOIN report_files rf
                    ON rf.id = gr.report_file_id
                ORDER BY gr.generated_at DESC NULLS LAST, gr.report_day DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )

    onedrive_root = _get_onedrive_report_root(db)

    generated_reports = []

    for row in generated_rows:
        item = dict(row)
        report_file_id = item.get("report_file_id")

        generated_reports.append(
            {
                "report_type": item.get("report_type"),
                "report_day": (
                    format_date_ddmmyyyy(item["report_day"])
                    if item.get("report_day")
                    else None
                ),
                "file_path": item.get("file_path"),
                "local_file_path": item.get("local_file_path"),
                "onedrive_path": item.get("onedrive_path"),
                "onedrive_web_url": item.get("onedrive_web_url"),
                "file_name": item.get("file_name")
                or Path(str(item.get("file_path") or "")).name,
                "file_url": (
                    f"/api/reports/files/{report_file_id}/download"
                    if report_file_id
                    else to_onedrive_report_url(
                        item.get("file_path"),
                        onedrive_root=onedrive_root,
                    )
                ),
                "status": item.get("status"),
                "notes": item.get("notes"),
                "generated_at": (
                    format_datetime_gmt8(item["generated_at"])
                    if item.get("generated_at")
                    else None
                ),
            }
        )

    summary = {
        "generated_reports_count": (
            len(monthly_reports) + len(troubleshooting_reports) + len(csv_reports)
        ),
        "monthly_reports_count": len(monthly_reports),
        "troubleshooting_reports_count": len(troubleshooting_reports),
        "csv_reports_count": len(csv_reports),
        "logged_generated_reports_count": len(generated_reports),
        "onedrive_report_dir": str(onedrive_root) if onedrive_root else None,
        "onedrive_warning": None,
        "primary_storage": "TigerData",
        "backup_storage": "OneDrive",
    }

    return {
        "summary": summary,
        "generated_reports": generated_reports,
        "monthly_reports": monthly_reports[:limit],
        "troubleshooting_reports": troubleshooting_reports[:limit],
        "csv_reports": csv_reports[:limit],
    }