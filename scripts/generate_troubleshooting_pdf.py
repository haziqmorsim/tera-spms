from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
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
from app.utils.time_utils import now_gmt8, today_gmt8

load_dotenv()

JOB_NAME = "generate_troubleshooting_pdf"

REPORTS_ROOT = Path("reports")
EXCEL_ROOT = REPORTS_ROOT / "excel"

EXCEL_ALARMS_DIR = EXCEL_ROOT / "alarms"
EXCEL_PLANTS_DIR = EXCEL_ROOT / "plants"
EXCEL_INVERTERS_DIR = EXCEL_ROOT / "inverters"
EXCEL_STRINGS_DIR = EXCEL_ROOT / "strings"

TROUBLESHOOTING_REPORTS_DIR = REPORTS_ROOT / "troubleshooting"

REPORT_FILE_REQUIREMENTS = {
    "active_alarms": {
        "directory": EXCEL_ALARMS_DIR,
        "prefix": "alarms_report_",
        "suffix": ".xlsx",
        "missing_message": "No alarms_report was generated for {date}.",
    },
    "low_performing_plants": {
        "directory": EXCEL_PLANTS_DIR,
        "prefix": "low_psh_plants_report_",
        "suffix": ".xlsx",
        "missing_message": "No low_psh_plants_report was generated for {date}.",
    },
    "low_performing_inverters": {
        "directory": EXCEL_INVERTERS_DIR,
        "prefix": "low_performing_inverters_report_",
        "suffix": ".xlsx",
        "missing_message": "No low_performing_inverters_report was generated for {date}.",
    },
    "low_performing_strings": {
        "directory": EXCEL_STRINGS_DIR,
        "prefix": "low_performing_strings_report_",
        "suffix": ".xlsx",
        "missing_message": "No low_performing_strings_report was generated for {date}.",
    },
}

TASKS = {
    "high_temperature": {
        "job_names": ["sync_high_temperature_inverters"],
        "label": "high-temperature inverter sync",
        "warning_key": "high_temperature_inverters",
    },
}


def _normalise_column_name(value: Any) -> str:
    text_value = str(value or "").strip().lower()
    text_value = text_value.replace("\n", " ")
    text_value = text_value.replace("\r", " ")

    for char in ["-", "/", "\\", ".", "(", ")", "%", "°"]:
        text_value = text_value.replace(char, " ")

    text_value = "_".join(text_value.split())

    replacements = {
        "run_day": "run_day",
        "plant": "plant_name",
        "plant_name": "plant_name",
        "site_plant": "plant_name",
        "site_name": "plant_name",
        "city": "city",
        "status": "status",
        "plant_status": "status",
        "total_capacity_kwp": "total_capacity_kwp",
        "total_string_capacity_kwp": "total_capacity_kwp",
        "grid_connected_date": "grid_connection_date",
        "grid_connection_date": "grid_connection_date",
        "plant_psh": "plant_avg_psh",
        "psh": "plant_avg_psh",
        "city_avg_psh": "overall_avg_psh",
        "overall_avg_psh": "overall_avg_psh",
        "threshold_psh": "threshold_psh",
        "deviation_pct_vs_city_avg": "psh_deviation_pct",
        "psh_deviation_pct_vs_city_avg": "psh_deviation_pct",
        "deviation": "psh_deviation_pct",
        "deviation_pct": "psh_deviation_pct",
        "underperforming": "underperforming",
        "reason": "reason",
        "inverter_name": "inverter_name",
        "inverter_number": "inverter_name",
        "inverter": "inverter_name",
        "inverter_sn": "inverter_sn",
        "sn_inverter": "inverter_sn",
        "sn": "inverter_sn",
        "inverter_psh": "inverter_psh",
        "benchmark_inverter_psh": "benchmark_inverter_psh",
        "threshold_inverter_psh": "threshold_inverter_psh",
        "deviation_pct_vs_benchmark": "deviation_pct_vs_benchmark",
        "string_name": "string_name",
        "string_number": "string_name",
        "string_total_current": "string_total_current",
        "benchmark_string_current": "benchmark_string_current",
        "threshold_string_current": "threshold_string_current",
        "device_name": "device_name",
        "device_sn": "device_sn",
        "alarm_name": "alarm_name",
        "severity": "severity",
        "occurrence_time": "occurrence_ts",
        "occurrence_ts": "occurrence_ts",
        "occurred_at": "occurrence_ts",
    }

    return replacements.get(text_value, text_value)


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned == "--":
            return None
        return cleaned

    return value


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None

        if pd.isna(value):
            return None

        result = float(value)

        if pd.isna(result):
            return None

        return result
    except Exception:
        return None


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    text_value = str(value).strip().lower()

    return text_value in {"true", "yes", "y", "1", "underperforming"}


def _find_exact_report_file(
    *,
    directory: Path,
    prefix: str,
    suffix: str,
    report_day_text: str,
) -> Path | None:
    """
    Find only the file for the exact report day.

    This intentionally does NOT fall back to older files.
    """

    if not directory.exists():
        return None

    matches = [
        file
        for file in directory.iterdir()
        if file.is_file()
        and file.name.lower().startswith(prefix.lower())
        and file.name.lower().endswith(suffix.lower())
        and report_day_text in file.name
    ]

    if not matches:
        return None

    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0]


def _read_excel_rows(file_path: Path) -> list[dict]:
    df = pd.read_excel(file_path)

    if df.empty:
        return []

    df.columns = [_normalise_column_name(col) for col in df.columns]

    rows: list[dict] = []

    for raw_row in df.to_dict(orient="records"):
        row = {key: _clean_value(value) for key, value in raw_row.items()}

        if not any(value is not None for value in row.values()):
            continue

        rows.append(row)

    return rows


def _load_required_excel_rows(
    *,
    section_key: str,
    report_day_text: str,
    section_warnings: dict[str, str],
) -> list[dict]:
    requirement = REPORT_FILE_REQUIREMENTS[section_key]

    report_file = _find_exact_report_file(
        directory=requirement["directory"],
        prefix=requirement["prefix"],
        suffix=requirement["suffix"],
        report_day_text=report_day_text,
    )

    if report_file is None:
        section_warnings[section_key] = requirement["missing_message"].format(
            date=report_day_text
        )
        return []

    return _read_excel_rows(report_file)


def fetch_active_alarms_from_excel(
    *,
    report_day_text: str,
    section_warnings: dict[str, str],
) -> list[dict]:
    rows = _load_required_excel_rows(
        section_key="active_alarms",
        report_day_text=report_day_text,
        section_warnings=section_warnings,
    )

    formatted_rows: list[dict] = []

    for row in rows:
        plant_name = row.get("plant_name")
        alarm_name = row.get("alarm_name")

        if not plant_name and not alarm_name:
            continue

        formatted_rows.append(
            {
                "plant_name": plant_name,
                "device_name": row.get("device_name"),
                "device_sn": row.get("device_sn"),
                "alarm_name": alarm_name,
                "severity": row.get("severity"),
                "occurrence_ts": row.get("occurrence_ts"),
            }
        )

    return formatted_rows


def fetch_low_performing_plants_from_excel(
    *,
    report_day_text: str,
    section_warnings: dict[str, str],
) -> list[dict]:
    rows = _load_required_excel_rows(
        section_key="low_performing_plants",
        report_day_text=report_day_text,
        section_warnings=section_warnings,
    )

    formatted_rows: list[dict] = []

    for row in rows:
        plant_name = row.get("plant_name")

        if not plant_name:
            continue

        underperforming = row.get("underperforming")

        if underperforming is not None and not _safe_bool(underperforming):
            continue

        formatted_rows.append(
            {
                "plant_name": plant_name,
                "plant_avg_psh": _safe_float(row.get("plant_avg_psh")),
                "overall_avg_psh": _safe_float(row.get("overall_avg_psh")),
                "psh_deviation_pct": _safe_float(row.get("psh_deviation_pct")),
            }
        )

    return formatted_rows


def fetch_low_performing_inverters_from_excel(
    *,
    report_day_text: str,
    section_warnings: dict[str, str],
) -> list[dict]:
    rows = _load_required_excel_rows(
        section_key="low_performing_inverters",
        report_day_text=report_day_text,
        section_warnings=section_warnings,
    )

    formatted_rows: list[dict] = []

    for row in rows:
        plant_name = row.get("plant_name")
        inverter_name = row.get("inverter_name")

        if not plant_name and not inverter_name:
            continue

        underperforming = row.get("underperforming")

        if underperforming is not None and not _safe_bool(underperforming):
            continue

        formatted_rows.append(
            {
                "plant_name": plant_name,
                "inverter_name": inverter_name,
                "inverter_sn": row.get("inverter_sn"),
                "inverter_psh": _safe_float(row.get("inverter_psh")),
                "benchmark_inverter_psh": _safe_float(
                    row.get("benchmark_inverter_psh")
                ),
                "deviation_pct_vs_benchmark": _safe_float(
                    row.get("deviation_pct_vs_benchmark")
                ),
                "reason": row.get("reason"),
            }
        )

    return formatted_rows


def fetch_low_performing_strings_from_excel(
    *,
    report_day_text: str,
    section_warnings: dict[str, str],
) -> list[dict]:
    rows = _load_required_excel_rows(
        section_key="low_performing_strings",
        report_day_text=report_day_text,
        section_warnings=section_warnings,
    )

    formatted_rows: list[dict] = []

    for row in rows:
        plant_name = row.get("plant_name")
        inverter_name = row.get("inverter_name")
        string_name = row.get("string_name")

        if not plant_name and not inverter_name and not string_name:
            continue

        underperforming = row.get("underperforming")

        if underperforming is not None and not _safe_bool(underperforming):
            continue

        formatted_rows.append(
            {
                "plant_name": plant_name,
                "inverter_name": inverter_name,
                "inverter_sn": row.get("inverter_sn"),
                "string_name": string_name,
                "string_total_current": _safe_float(row.get("string_total_current")),
                "benchmark_string_current": _safe_float(
                    row.get("benchmark_string_current")
                ),
                "deviation_pct_vs_benchmark": _safe_float(
                    row.get("deviation_pct_vs_benchmark")
                ),
                "reason": row.get("reason"),
            }
        )

    return formatted_rows


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


def main():
    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)

        report_day = today_gmt8() - timedelta(days=1)
        report_day_text = report_day.strftime("%d-%m-%Y")
        generated_at = now_gmt8()

        section_warnings: dict[str, str] = {}
        job_status_meta: dict[str, dict] = {}

        low_performing_plants = fetch_low_performing_plants_from_excel(
            report_day_text=report_day_text,
            section_warnings=section_warnings,
        )

        low_performing_inverters = fetch_low_performing_inverters_from_excel(
            report_day_text=report_day_text,
            section_warnings=section_warnings,
        )

        low_performing_strings = fetch_low_performing_strings_from_excel(
            report_day_text=report_day_text,
            section_warnings=section_warnings,
        )

        active_alarms = fetch_active_alarms_from_excel(
            report_day_text=report_day_text,
            section_warnings=section_warnings,
        )

        high_temperature_inverters: list[dict] = []

        ok, warning, status = _task_succeeded(db, "high_temperature", report_day)
        job_status_meta["high_temperature"] = {
            "job_name": status.job_name,
            "exists": status.exists,
            "success": status.success,
            "status": status.status,
            "details": status.details,
        }

        if ok:
            high_temperature_inverters = fetch_high_temperature_inverters(
                db,
                report_day,
            )
        else:
            section_warnings["high_temperature_inverters"] = warning

        TROUBLESHOOTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        filename = f"troubleshooting_report_{report_day_text}.pdf"
        output_path = TROUBLESHOOTING_REPORTS_DIR / filename

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
            f"Troubleshooting report day: {report_day_text}\n"
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
                "report_day": str(report_day),
                "low_performing_count": len(low_performing_plants),
                "low_performing_inverter_count": len(low_performing_inverters),
                "low_performing_string_count": len(low_performing_strings),
                "active_alarm_count": len(active_alarms),
                "high_temperature_count": len(high_temperature_inverters),
                "section_warnings": section_warnings,
                "job_status": job_status_meta,
                "data_source": {
                    "active_alarms": "previous_day_excel",
                    "low_performing_plants": "previous_day_excel",
                    "low_performing_inverters": "previous_day_excel",
                    "low_performing_strings": "previous_day_excel",
                    "high_temperature_inverters": "previous_day_database",
                },
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