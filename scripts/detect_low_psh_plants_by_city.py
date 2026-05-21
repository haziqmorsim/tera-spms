from __future__ import annotations
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.low_psh_xlsx_report_service import build_low_psh_xlsx_report
from app.services.plant_psh_troubleshooting_service import fetch_and_detect_low_psh_by_city
from app.services.report_path_service import EXCEL_PLANTS_DIR, ensure_report_directories
from app.services.report_storage_service import save_generated_report
from app.utils.job_logger import start_run, finish_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "detect_low_psh_plants_by_city"
PLANT_INFO_EXCEL = Path("Service Performance Monitoring System Plant Information.xlsx")

OUTPUT_XLSX = (EXCEL_PLANTS_DIR / f"low_psh_plants_report_{datetime.now().strftime('%d-%m-%Y')}.xlsx")

def _clean_date(value):
    if value is None or value == "":
        return None

    try:
        if hasattr(value, "date"):
            return value.date()
    except Exception:
        pass

    return str(value)

def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

def persist_latest_low_psh_snapshot(report_df) -> int:
    under = report_df[report_df["underperforming"] == True].copy()
    run_day = today_gmt8()

    db = SessionLocal()

    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS low_psh_plants_by_city_latest (
                    run_day date NOT NULL,
                    plant_name text NOT NULL,
                    city text,
                    psh double precision,
                    city_avg_psh double precision,
                    threshold_psh double precision,
                    psh_deviation_pct_vs_city_avg double precision,
                    performance_status text,
                    underperforming boolean NOT NULL DEFAULT false,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (run_day, plant_name)
                )
                """
            )
        )

        db.execute(
            text(
                """
                ALTER TABLE low_psh_plants_by_city_latest
                ADD COLUMN IF NOT EXISTS plant_status text
                """
            )
        )

        db.execute(
            text(
                """
                ALTER TABLE low_psh_plants_by_city_latest
                ADD COLUMN IF NOT EXISTS total_string_capacity_kwp double precision
                """
            )
        )

        db.execute(
            text(
                """
                ALTER TABLE low_psh_plants_by_city_latest
                ADD COLUMN IF NOT EXISTS grid_connection_date date
                """
            )
        )

        db.execute(
            text(
                """
                DELETE FROM low_psh_plants_by_city_latest
                WHERE run_day = :run_day
                """
            ),
            {"run_day": run_day},
        )

        for _, row in under.iterrows():
            db.execute(
                text(
                    """
                    INSERT INTO low_psh_plants_by_city_latest (
                        run_day,
                        plant_name,
                        city,
                        psh,
                        city_avg_psh,
                        threshold_psh,
                        psh_deviation_pct_vs_city_avg,
                        performance_status,
                        underperforming,
                        plant_status,
                        total_string_capacity_kwp,
                        grid_connection_date
                    )
                    VALUES (
                        :run_day,
                        :plant_name,
                        :city,
                        :psh,
                        :city_avg_psh,
                        :threshold_psh,
                        :psh_deviation_pct_vs_city_avg,
                        :performance_status,
                        true,
                        :plant_status,
                        :total_string_capacity_kwp,
                        :grid_connection_date
                    )
                    ON CONFLICT (run_day, plant_name)
                    DO UPDATE SET
                        city = EXCLUDED.city,
                        psh = EXCLUDED.psh,
                        city_avg_psh = EXCLUDED.city_avg_psh,
                        threshold_psh = EXCLUDED.threshold_psh,
                        psh_deviation_pct_vs_city_avg = EXCLUDED.psh_deviation_pct_vs_city_avg,
                        performance_status = EXCLUDED.performance_status,
                        underperforming = EXCLUDED.underperforming,
                        plant_status = EXCLUDED.plant_status,
                        total_string_capacity_kwp = EXCLUDED.total_string_capacity_kwp,
                        grid_connection_date = EXCLUDED.grid_connection_date,
                        created_at = now()
                    """
                ),
                {
                    "run_day": run_day,
                    "plant_name": row["plant_name"],
                    "city": row["city"],
                    "psh": _safe_float(row.get("psh")),
                    "city_avg_psh": _safe_float(row.get("city_avg_psh")),
                    "threshold_psh": _safe_float(row.get("threshold_psh")),
                    "psh_deviation_pct_vs_city_avg": _safe_float(
                        row.get("psh_deviation_pct_vs_city_avg")
                    ),
                    "performance_status": row.get("performance_status"),
                    "plant_status": row.get("status"),
                    "total_string_capacity_kwp": _safe_float(
                        row.get("total_string_capacity_kwp")
                    ),
                    "grid_connection_date": _clean_date(row.get("grid_connection_date")),
                },
            )

        db.commit()
        return len(under)

    finally:
        db.close()

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        ensure_report_directories()

        run_id = start_run(db, JOB_NAME)

        if not PLANT_INFO_EXCEL.exists():
            raise FileNotFoundError(
                "Plant Information Excel file was not found. Place the file in the project root as "
                f"'{PLANT_INFO_EXCEL.name}' or update PLANT_INFO_EXCEL in the script."
            )

        report_df = fetch_and_detect_low_psh_by_city(
            PLANT_INFO_EXCEL,
            underperformance_pct=10,
            max_pages=20,
            headless=False,
        )

        OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
        build_low_psh_xlsx_report(report_df, OUTPUT_XLSX)

        persisted_count = persist_latest_low_psh_snapshot(report_df)

        save_generated_report(
            report_type="LOW_PSH_XLSX",
            file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            local_file_path=str(OUTPUT_XLSX).replace("\\", "/"),
            report_day=today_gmt8(),
        )

        under = report_df[report_df["underperforming"] == True].copy()
        under_count = len(under)

        message = (
            f"Low-performing plants: {under_count}\n"
            f"File: {OUTPUT_XLSX.name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "underperforming_count": under_count,
                "persisted_count": persisted_count,
                "file_name": OUTPUT_XLSX.name,
                "file_path": str(OUTPUT_XLSX).replace("\\", "/"),
            },
        )

        print(f"Number of underperforming plants: {under_count}")

        if under.empty:
            print("No underperforming plants were detected based on city average PSH.")
        else:
            print("Underperforming plants:\n")

            for _, row in under.iterrows():
                print(
                    f"City: {row['city']} | Plant: {row['plant_name']} | "
                    f"PSH: {row['psh']:.3f} | City Average PSH: {row['city_avg_psh']:.3f} | "
                    f"Threshold: {row['threshold_psh']:.3f} | "
                    f"Deviation: {row['psh_deviation_pct_vs_city_avg']:.2f}%"
                )

        print(f"\nFull report is saved to {OUTPUT_XLSX}")

    except Exception as e:
        db.rollback()

        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))

        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()