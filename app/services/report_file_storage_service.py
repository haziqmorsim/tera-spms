from __future__ import annotations
import hashlib
import mimetypes
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_CONTENT_TYPE = "application/pdf"

def _normalise_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    
    return str(value).replace("\\", "/")

def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        return EXCEL_CONTENT_TYPE
    
    if suffix == ".pdf":
        return PDF_CONTENT_TYPE
    
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or "application/octet-stream"

def _read_file_bytes(path: str | Path) -> bytes:
    file_path = Path(path)

    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Report file not found: {file_path}")
    
    return file_path.read_bytes()

def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None
    
def ensure_report_files_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS report_files (
                id bigserial PRIMARY KEY,
                report_type text NOT NULL,
                report_day date,
                file_name text NOT NULL,
                content_type text NOT NULL,
                file_ext text NOT NULL,
                file_size_bytes bigint NOT NULL,
                file_sha256 text NOT NULL,
                file_data bytea NOT NULL,
                local_file_path text,
                onedrive_path text,
                onedrive_web_url text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT uq_report_files_type_day_name UNIQUE (
                    report_type,
                    report_day,
                    file_name
                )
            )
            """
        )
    )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_report_files_report_type_day
            ON report_files (report_type, report_day DESC)
            """
        )
    )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_report_files_created_at
            ON report_files (created_at DESC)
            """
        )
    )

    db.execute(
        text(
            """
            ALTER TABLE generated_reports
            ADD COLUMN IF NOT EXISTS report_file_id bigint
            """
        )
    )

    db.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_generated_reports_report_file_id'
                ) THEN
                    ALTER TABLE generated_reports
                    ADD CONSTRAINT fk_generated_reports_report_file_id
                    FOREIGN KEY (report_file_id)
                    REFERENCES report_files(id)
                    ON DELETE SET NULL;
                END IF;
            END $$;
            """
        )
    )

def store_report_file_in_db(
    db: Session, 
    *, 
    report_type: str, 
    report_day: date | datetime | None, 
    file_path: str | Path, 
    local_file_path: str | Path | None = None, 
    onedrive_path: str | Path | None = None, 
    onedrive_web_url: str | Path | None = None, 
) -> int:
    ensure_report_files_table(db)

    source_path = Path(local_file_path or file_path)
    file_bytes = _read_file_bytes(source_path)

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    content_type = _guess_content_type(source_path)

    if isinstance(report_day, datetime):
        report_day = report_day.date()

    row_id = db.execute(
        text(
            """
            INSERT INTO report_files (
                report_type,
                report_day,
                file_name,
                content_type,
                file_ext,
                file_size_bytes,
                file_sha256,
                file_data,
                local_file_path,
                onedrive_path,
                onedrive_web_url
            )
            VALUES (
                :report_type,
                :report_day,
                :file_name,
                :content_type,
                :file_ext,
                :file_size_bytes,
                :file_sha256,
                :file_data,
                :local_file_path,
                :onedrive_path,
                :onedrive_web_url
            )
            ON CONFLICT (report_type, report_day, file_name)
            DO UPDATE SET
                content_type = EXCLUDED.content_type,
                file_ext = EXCLUDED.file_ext,
                file_size_bytes = EXCLUDED.file_size_bytes,
                file_sha256 = EXCLUDED.file_sha256,
                file_data = EXCLUDED.file_data,
                local_file_path = EXCLUDED.local_file_path,
                onedrive_path = COALESCE(EXCLUDED.onedrive_path, report_files.onedrive_path),
                onedrive_web_url = COALESCE(EXCLUDED.onedrive_web_url, report_files.onedrive_web_url),
                updated_at = now()
            RETURNING id
            """
        ), 
        {
            "report_type": report_type, 
            "report_day": report_day, 
            "file_name": source_path.name, 
            "content_type": content_type, 
            "file_ext": source_path.suffix.lower(), 
            "file_size_bytes": len(file_bytes), 
            "file_sha256": file_hash, 
            "file_data": file_bytes, 
            "local_file_path": _normalise_path(source_path), 
            "onedrive_path": _normalise_path(onedrive_path), 
            "onedrive_web_url": onedrive_web_url,
        },
    ).scalar_one()

    return int(row_id)

def update_report_file_onedrive_backup(
    db: Session, 
    *, 
    report_file_id: int, 
    onedrive_path: str | Path | None, 
    onedrive_web_url: str | None = None,
) -> None:
    ensure_report_files_table(db)

    db.execute(
        text(
            """
            UPDATE report_files
            SET
                onedrive_path = :onedrive_path,
                onedrive_web_url = :onedrive_web_url,
                updated_at = now()
            WHERE id = :report_file_id
            """
        ), 
        {
            "report_file_id": report_file_id, 
            "onedrive_path": _normalise_path(onedrive_path), 
            "onedrive_web_url": onedrive_web_url,
        },
    )

def update_report_file_onedrive_backup_by_local_file(
    db: Session, 
    *, 
    local_file_path: str | Path, 
    onedrive_path: str | Path | None, 
    onedrive_web_url: str | None = None,
) -> int | None:
    ensure_report_files_table(db)

    normalised_local_path = _normalise_path(local_file_path)

    row = (
        db.execute(
            text(
                """
                SELECT id
                FROM report_files
                WHERE local_file_path = :local_file_path
                   OR replace(local_file_path, '\\', '/') = :local_file_path
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ), 
            {"local_file_path": normalised_local_path},
        )
        .mappings()
        .first()
    )

    if not row:
        return None
    
    report_file_id = int(row["id"])

    update_report_file_onedrive_backup(
        db, 
        report_file_id=report_file_id, 
        onedrive_path=onedrive_path, 
        onedrive_web_url=onedrive_web_url,
    )

    return report_file_id

def get_report_file_for_download(
    db: Session, 
    *, 
    report_file_id: int,
) -> dict | None:
    ensure_report_files_table(db)

    row = (
        db.execute(
            text(
                """
                SELECT
                    id,
                    report_type,
                    report_day,
                    file_name,
                    content_type,
                    file_size_bytes,
                    file_data
                FROM report_files
                WHERE id = :id
                LIMIT 1
                """
            ), 
            {"id": report_file_id},
        )
        .mappings()
        .first()
    )

    return dict(row) if row else None

def find_report_file_for_day(
    db: Session, 
    *, 
    report_types: list[str], 
    report_day, 
    file_prefix: str, 
    file_suffix: str, 
) -> dict | None:
    ensure_report_files_table(db)

    if isinstance(report_day, datetime):
        report_day = report_day.date()

    report_types_upper = [item.upper() for item in report_types]

    rows = (
        db.execute(
            text(
                """
                SELECT
                    id,
                    report_type,
                    report_day,
                    file_name,
                    content_type,
                    file_size_bytes,
                    local_file_path,
                    onedrive_path,
                    onedrive_web_url,
                    created_at,
                    updated_at
                FROM report_files
                WHERE upper(report_type) = ANY(:report_types)
                  AND report_day = :report_day
                  AND lower(file_name) LIKE lower(:file_pattern)
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """
            ), 
            {
                "report_types": report_types_upper, 
                "report_day": report_day, 
                "file_pattern": f"{file_prefix}%{file_suffix}",
            },
        )
        .mappings()
        .all()
    )

    if not rows:
        return None
    
    return dict(rows[0])

def materialise_report_file_from_db(
    db: Session, 
    *, 
    report_file_id: int, 
    output_dir: str | Path | None = None,
) -> Path:
    row = get_report_file_for_download(db, report_file_id=report_file_id)

    if not row:
        raise FileNotFoundError(f"Report file not found in database: {report_file_id}")
    
    if output_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="tera_spms_report_"))
    else:
        temp_dir = output_dir

    temp_dir.mkdir(parents=True, exist_ok=True)

    output_path = temp_dir / row["file_name"]
    output_path.write_bytes(bytes(row["file_data"]))

    return output_path

def fetch_report_file_items(limit: int = 200, db: Session | None = None) -> list[dict]:
    close_db = False

    if db is None:
        from app.db.session import SessionLocal

        db = SessionLocal
        close_db = True

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
                        content_type,
                        file_ext,
                        file_size_bytes,
                        local_file_path,
                        onedrive_path,
                        onedrive_web_url,
                        created_at,
                        updated_at
                    FROM report_files
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT :limit
                    """
                ), 
                {"limit": limit},
            )
            .mappings()
            .all()
        )

        items: list[dict] = []

        for row in rows:
            item = dict(row)
            item["id"] = _safe_int(item.get("id"))
            item["file_url"] = f"/api/reports/files/{item['id']}/download"
            item["file_path"] = item.get("local_file_path") or item.get("onedrive_path")

        return items
    
    finally:
        if close_db:
            db.close()