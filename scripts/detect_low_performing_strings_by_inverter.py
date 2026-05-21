from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError
from app.db.session import SessionLocal, engine
from app.services.low_performing_string_xlsx_report_service import build_low_performing_string_xlsx_report
from app.services.report_path_service import EXCEL_STRINGS_DIR, ensure_report_directories
from app.services.report_storage_service import save_generated_report
from app.services.string_current_troubleshooting_service import (
    fetch_and_detect_low_performing_strings_from_fusionsolar,
    fetch_latest_low_performing_inverters,
    persist_low_performing_strings,
)
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "detect_low_performing_strings_by_inverter"

OUTPUT_XLSX = (EXCEL_STRINGS_DIR / f"low_performing_strings_report_{datetime.now().strftime('%d-%m-%Y')}.xlsx")

def _start_job_and_fetch_inverters():
    db = SessionLocal()

    try:
        run_id = start_run(db, JOB_NAME)
        inverters = fetch_latest_low_performing_inverters(db)
        return run_id, inverters

    finally:
        db.close()

def _persist_rows_with_retry(rows: list[dict], report_day) -> int:
    last_error: Exception | None = None

    for attempt in range(1, 3):
        db = SessionLocal()

        try:
            return persist_low_performing_strings(
                db,
                rows,
                run_day=report_day,
            )

        except OperationalError as exc:
            last_error = exc
            db.rollback()
            db.close()

            print(
                f"Database connection failed while saving string results "
                f"(attempt {attempt}/2). Retrying with a fresh connection..."
            )

            engine.dispose()
            time.sleep(5)

        except Exception:
            db.rollback()
            raise

        finally:
            try:
                db.close()
            except Exception:
                pass

    raise RuntimeError(
        "Failed to persist low-performing string results after retrying. "
        "The database connection was closed by the server."
    ) from last_error

def _finish_job_success(run_id: int, message: str, meta: dict) -> None:
    db = SessionLocal()

    try:
        finish_run(
            db,
            run_id,
            "success",
            message,
            meta,
        )

    finally:
        db.close()

def _finish_job_fail(run_id: int | None, error_message: str) -> None:
    if run_id is None:
        return

    db = SessionLocal()

    try:
        finish_run(
            db,
            run_id,
            "fail",
            error_message,
        )

    except Exception:
        db.rollback()

    finally:
        db.close()

def main() -> None:
    run_id = None

    try:
        ensure_report_directories()

        report_day = today_gmt8()

        run_id, inverters = _start_job_and_fetch_inverters()

        if not inverters:
            rows: list[dict] = []
        else:
            rows = fetch_and_detect_low_performing_strings_from_fusionsolar(
                inverters,
                report_day=report_day,
                headless=False,
                interactive_login=True,
            )

        OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)

        build_low_performing_string_xlsx_report(rows, OUTPUT_XLSX)

        persisted_count = _persist_rows_with_retry(
            rows,
            report_day=report_day,
        )

        save_generated_report(
            report_type="LOW_PERFORMING_STRING_XLSX",
            file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            local_file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            report_day=report_day,
        )

        message = (
            f"Low-performing inverters checked: {len(inverters)}\n"
            f"Low-performing strings: {len(rows)}\n"
            f"File: {OUTPUT_XLSX.name}"
        )

        _finish_job_success(
            run_id,
            message,
            {
                "low_performing_inverter_count": len(inverters),
                "low_performing_string_count": len(rows),
                "persisted_count": persisted_count,
                "file_name": OUTPUT_XLSX.name,
                "file_path": str(OUTPUT_XLSX).replace("\\", "/"),
            },
        )

        print(message)

        if rows:
            print("\nLow-performing strings:")

            for row in rows:
                print(
                    f"Plant: {row['plant_name']} | "
                    f"Inverter: {row['inverter_name']} | "
                    f"String: {row['string_name']} | "
                    f"Total Current: {row['string_total_current']:.3f} | "
                    f"Benchmark: {row['benchmark_string_current']:.3f} | "
                    f"Deviation: {row['deviation_pct_vs_benchmark']:.2f}%"
                )
        else:
            print("No low-performing strings were detected.")

    except Exception as exc:
        _finish_job_fail(run_id, str(exc))
        raise


if __name__ == "__main__":
    main()