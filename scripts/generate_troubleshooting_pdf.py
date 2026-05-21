from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.job_run_status_service import (
    get_latest_job_status_for_day,
    unsuccessful_message,
)
from app.services.pdf_report_service import build_troubleshooting_pdf
from app.services.report_storage_service import save_generated_report
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import format_datetime_gmt8, now_gmt8, today_gmt8

load_dotenv()

JOB_NAME = "generate_troubleshooting_pdf"

TASKS = {
    "alarms": {
        "job_names": ["poll_alarms"],
        "label": "alarm polling",
        "warning_key": "active_alarms",
    },
    "high_temperature": {
        "job_names": ["sync_high_temperature_inverters"],
        "label": "high-temperature inverter sync",
        "warning_key": "high_temperature_inverters",
    },
    "low_psh_plants": {
        # Keep both names here so the report still works if the job is renamed.
        "job_names": [
            "detect_low_performing_plants_by_city",
            "detect_low_psh_plants_by_city",
        ],
        "label": "low-PSH plant detection",
        "warning_key": "low_performing_plants",
    },
    "low_performing_inverters": {
        "job_names": ["detect_low_performing_inverters_by_plant"],
        "label": "low-performing inverter detection",
        "warning_key": "low_performing_inverters",
    },
    "low_performing_strings": {
        "job_names": ["detect_low_performing_strings_by_inverter"],
        "label": "low-performing string detection",
        "warning_key": "low_performing_strings",
    },
}

def _task_succeeded(db, task_key: str, report_day):
    task = TASKS[task_key]
    status = get_latest_job_status_for_day(
        db,
        job_names=task["job_names"],
        report_day=report_day,
    )

    if status.success:
        return True, None, status

    return (
        False,
        unsuccessful_message(task["label"], report_day),
        status,
    )

def fetch_active_alarms(db):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    plant_name,
                    device_name,
                    device_sn,
                    alarm_name,
                    severity,
                    occurrence_ts
                FROM alarms
                WHERE is_active = true
                ORDER BY plant_name ASC, occurrence_ts DESC
                """
            )
        )
        .mappings()
        .all()
    )

    formatted_rows = []

    for r in rows:
        item = dict(r)

        if item.get("occurrence_ts"):
            dt_text = format_datetime_gmt8(item["occurrence_ts"])
            parts = dt_text.split(" ")
            item["occurrence_ts"] = (
                f"{parts[0]} {parts[1][:5]}" if len(parts) >= 2 else dt_text
            )

        formatted_rows.append(item)

    return formatted_rows

def fetch_high_temperature_inverters(db, report_day):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    plant_name,
                    device_name,
                    device_sn,
                    internal_temperature_c
                FROM high_temperature_inverters_latest
                WHERE run_day = :report_day
                ORDER BY plant_name ASC, device_name ASC
                """
            ),
            {"report_day": report_day},
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in rows]

def fetch_low_performing_plants(db, report_day):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    plant_name,
                    psh AS plant_avg_psh,
                    city_avg_psh AS overall_avg_psh,
                    psh_deviation_pct_vs_city_avg AS psh_deviation_pct
                FROM low_psh_plants_by_city_latest
                WHERE run_day = :report_day
                  AND underperforming = true
                ORDER BY plant_name ASC
                """
            ),
            {"report_day": report_day},
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in rows]

def fetch_low_performing_inverters(db, report_day):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    plant_name,
                    inverter_name,
                    inverter_sn,
                    inverter_psh,
                    benchmark_inverter_psh,
                    deviation_pct_vs_benchmark,
                    reason
                FROM low_performing_inverters_latest
                WHERE run_day = :report_day
                  AND underperforming = true
                ORDER BY plant_name ASC, inverter_name ASC
                """
            ),
            {"report_day": report_day},
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in rows]

def fetch_low_performing_strings(db, report_day):
    rows = (
        db.execute(
            text(
                """
                SELECT
                    plant_name,
                    inverter_name,
                    inverter_sn,
                    string_name,
                    string_total_current,
                    benchmark_string_current,
                    deviation_pct_vs_benchmark,
                    reason
                FROM low_performing_strings_latest
                WHERE run_day = :report_day
                  AND underperforming = true
                ORDER BY plant_name ASC, inverter_name ASC, string_name ASC
                """
            ),
            {"report_day": report_day},
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in rows]

def main():
    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)

        report_day = today_gmt8()
        generated_at = now_gmt8()

        section_warnings: dict[str, str] = {}
        job_status_meta: dict[str, dict] = {}

        low_performing_plants: list[dict] = []
        low_performing_inverters: list[dict] = []
        low_performing_strings: list[dict] = []
        active_alarms: list[dict] = []
        high_temperature_inverters: list[dict] = []

        ok, warning, status = _task_succeeded(db, "low_psh_plants", report_day)
        job_status_meta["low_psh_plants"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            low_performing_plants = fetch_low_performing_plants(db, report_day)
        else:
            section_warnings["low_performing_plants"] = warning

        ok, warning, status = _task_succeeded(db, "low_performing_inverters", report_day)
        job_status_meta["low_performing_inverters"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            low_performing_inverters = fetch_low_performing_inverters(db, report_day)
        else:
            section_warnings["low_performing_inverters"] = warning

        ok, warning, status = _task_succeeded(db, "low_performing_strings", report_day)
        job_status_meta["low_performing_strings"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            low_performing_strings = fetch_low_performing_strings(db, report_day)
        else:
            section_warnings["low_performing_strings"] = warning

        ok, warning, status = _task_succeeded(db, "alarms", report_day)
        job_status_meta["alarms"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            active_alarms = fetch_active_alarms(db)
        else:
            section_warnings["active_alarms"] = warning

        ok, warning, status = _task_succeeded(db, "high_temperature", report_day)
        job_status_meta["high_temperature"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            high_temperature_inverters = fetch_high_temperature_inverters(db, report_day)
        else:
            section_warnings["high_temperature_inverters"] = warning

        out_dir = Path("reports") / "troubleshooting"
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"troubleshooting_report_{report_day.strftime('%d-%m-%Y')}.pdf"
        output_path = out_dir / filename

        build_troubleshooting_pdf(
            output_path=output_path,
            report_day=report_day,
            generated_at=generated_at,
            prepared_by="TERA SPMS",
            low_performing_plants=low_performing_plants,
            active_alarms=active_alarms,
            high_temperature_inverters=high_temperature_inverters,
            low_performing_inverters=low_performing_inverters,
            low_performing_strings=low_performing_strings,
            section_warnings=section_warnings,
        )

        save_generated_report(
            report_type="TROUBLESHOOTING_PDF",
            file_path=str(output_path).replace("\\", "/"),
            local_file_path=str(output_path).replace("\\", "/"),
            report_day=report_day,
        )

        message = (
            f"Low-performing plants: {len(low_performing_plants)}\n"
            f"Low-performing inverters: {len(low_performing_inverters)}\n"
            f"Low-performing strings: {len(low_performing_strings)}\n"
            f"Alarms: {len(active_alarms)}\n"
            f"High-temperature inverters: {len(high_temperature_inverters)}\n"
            f"Warnings: {len(section_warnings)}\n"
            f"File: {output_path.name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "file_name": output_path.name,
                "file_path": str(output_path).replace("\\", "/"),
                "low_performing_count": len(low_performing_plants),
                "low_performing_inverter_count": len(low_performing_inverters),
                "low_performing_string_count": len(low_performing_strings),
                "active_alarm_count": len(active_alarms),
                "high_temperature_count": len(high_temperature_inverters),
                "section_warnings": section_warnings,
                "job_status": job_status_meta,
            },
        )

        print(message)

        if section_warnings:
            print("\nWarnings:")
            for warning in section_warnings.values():
                print(f"- {warning}")

    except Exception as e:
        db.rollback()

        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))

        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()