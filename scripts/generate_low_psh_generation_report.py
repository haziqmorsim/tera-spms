from __future__ import annotations
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.overall_low_psh_generation_xlsx_report_service import (
    build_latest_overall_low_psh_generation_xlsx_report,
    fetch_overall_low_psh_generation_rows,
    resolve_low_psh_generation_report_day,
)
from app.services.report_path_service import EXCEL_OVERALL_DIR, ensure_report_directories
from app.services.report_storage_service import save_generated_report
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "generate_low_psh_generation_report"

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        ensure_report_directories()

        run_id = start_run(db, JOB_NAME)

        report_day = resolve_low_psh_generation_report_day(db) or today_gmt8()

        output_path = (
            EXCEL_OVERALL_DIR
            / f"low_psh_generation_report_{report_day.strftime('%d-%m-%Y')}.xlsx"
        )

        rows = fetch_overall_low_psh_generation_rows(
            db,
            report_day=report_day,
        )

        build_latest_overall_low_psh_generation_xlsx_report(
            db,
            report_day=report_day,
            output_path=output_path,
        )

        save_generated_report(
            report_type="LOW_PSH_GENERATION_XLSX",
            file_path=str(output_path).replace("\\", "/"),
            local_file_path=str(output_path).replace("\\", "/"),
            report_day=report_day,
        )

        message = (
            f"Low-PSH generation records: {len(rows)}\n"
            f"File: {output_path.name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "report_day": str(report_day),
                "row_count": len(rows),
                "file_name": output_path.name,
                "file_path": str(output_path).replace("\\", "/"),
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