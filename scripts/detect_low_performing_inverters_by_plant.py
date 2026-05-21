from __future__ import annotations
from datetime import datetime
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.inverter_psh_troubleshooting_service import (
    fetch_and_detect_low_performing_inverters_from_fusionsolar,
    load_underperforming_plants_for_inverter_check,
    persist_low_performing_inverters,
)
from app.services.low_performing_inverter_xlsx_report_service import (
    build_low_performing_inverter_xlsx_report,
)
from app.services.report_path_service import EXCEL_INVERTERS_DIR, ensure_report_directories
from app.services.report_storage_service import save_generated_report
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "detect_low_performing_inverters_by_plant"

OUTPUT_XLSX = (EXCEL_INVERTERS_DIR / f"low_performing_inverters_report_{datetime.now().strftime('%d-%m-%Y')}.xlsx")

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        ensure_report_directories()

        run_id = start_run(db, JOB_NAME)
        report_day = today_gmt8()

        plants = load_underperforming_plants_for_inverter_check(
            db,
            prefer_excel=True,
        )

        if not plants:
            rows: list[dict] = []
        else:
            rows = fetch_and_detect_low_performing_inverters_from_fusionsolar(
                plants,
                report_day=report_day,
                headless=False,
                interactive_login=True,
            )

        OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)

        build_low_performing_inverter_xlsx_report(rows, OUTPUT_XLSX)

        persisted_count = persist_low_performing_inverters(
            db,
            rows,
            run_day=report_day,
        )

        save_generated_report(
            report_type="LOW_PERFORMING_INVERTER_XLSX",
            file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            local_file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            report_day=report_day,
        )

        message = (
            f"Low-PSH plants checked: {len(plants)}\n"
            f"Low-performing inverters: {len(rows)}\n"
            f"File: {OUTPUT_XLSX.name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "low_psh_plant_count": len(plants),
                "low_performing_inverter_count": len(rows),
                "persisted_count": persisted_count,
                "file_name": OUTPUT_XLSX.name,
                "file_path": str(OUTPUT_XLSX).replace("\\", "/"),
            },
        )

        print(message)

        if rows:
            print("\nLow-performing inverters:")

            for row in rows:
                print(
                    f"Plant: {row['plant_name']} | "
                    f"Inverter: {row['inverter_name']} | "
                    f"PSH: {row['inverter_psh']:.3f} | "
                    f"Benchmark: {row['benchmark_inverter_psh']:.3f} | "
                    f"Deviation: {row['deviation_pct_vs_benchmark']:.2f}%"
                )
        else:
            print("No low-performing inverters were detected.")

    except Exception as exc:
        db.rollback()

        if run_id is not None:
            finish_run(db, run_id, "fail", str(exc))

        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()