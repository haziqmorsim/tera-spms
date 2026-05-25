from __future__ import annotations
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.utils.time_utils import format_datetime_gmt8, today_gmt8

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

def _json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)

    if isinstance(value, datetime):
        return format_datetime_gmt8(value)

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    return value

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return None

        return result

    except Exception:
        return None

def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return 0

        return int(result)

    except Exception:
        return 0

def _safe_deviation_pct(psh: Any, city_avg_psh: Any, existing_value: Any = None) -> float | None:
    existing = _safe_float(existing_value)

    if existing is not None:
        return existing

    psh_value = _safe_float(psh)
    avg_value = _safe_float(city_avg_psh)

    if psh_value is None or avg_value is None or avg_value == 0:
        return None

    result = ((psh_value - avg_value) / avg_value) * 100

    if math.isnan(result) or math.isinf(result):
        return None

    return round(result, 2)

def _get_value(row: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]

    return default

def _get_latest_low_psh_run_day(db: Session) -> date | None:
    try:
        return (
            db.execute(
                text(
                    """
                    SELECT MAX(run_day)
                    FROM low_psh_plants_by_city_latest
                    """
                )
            )
            .scalar_one_or_none()
        )
    except Exception:
        db.rollback()
        return None

def _get_latest_high_temperature_run_day(db: Session) -> date | None:
    try:
        return (
            db.execute(
                text(
                    """
                    SELECT MAX(run_day)
                    FROM high_temperature_inverters_latest
                    """
                )
            )
            .scalar_one_or_none()
        )
    except Exception:
        db.rollback()
        return None

def _fetch_kpi_counts(
    db: Session,
    *,
    low_psh_run_day: date | None,
    high_temperature_run_day: date | None,
) -> dict:
    low_plant_count = 0
    alarm_count = 0
    high_temp_count = 0

    if low_psh_run_day is not None:
        try:
            low_plant_count = _safe_int(
                db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM low_psh_plants_by_city_latest
                        WHERE run_day = :run_day
                          AND underperforming = true
                        """
                    ),
                    {"run_day": low_psh_run_day},
                ).scalar_one_or_none()
            )
        except Exception:
            db.rollback()

    try:
        alarm_count = _safe_int(
            db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM alarms
                    WHERE is_active = true
                    """
                )
            ).scalar_one_or_none()
        )
    except Exception:
        db.rollback()

    if high_temperature_run_day is not None:
        try:
            high_temp_count = _safe_int(
                db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM high_temperature_inverters_latest
                        WHERE run_day = :run_day
                        """
                    ),
                    {"run_day": high_temperature_run_day},
                ).scalar_one_or_none()
            )
        except Exception:
            db.rollback()

    return {
        "low_performing_plants": low_plant_count,
        "active_alarms": alarm_count,
        "high_temperature_inverters": high_temp_count,
    }

def _fetch_low_performing_plants(
    db: Session,
    *,
    run_day: date | None,
) -> list[dict]:
    if run_day is None:
        return []

    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT *
                    FROM low_psh_plants_by_city_latest
                    WHERE run_day = :run_day
                      AND underperforming = true
                    ORDER BY plant_name ASC
                    """
                ),
                {"run_day": run_day},
            )
            .mappings()
            .all()
        )

        result: list[dict] = []

        for row in rows:
            item = dict(row)

            psh = _safe_float(_get_value(item, "psh", "plant_psh", "plant_avg_psh"))
            city_avg_psh = _safe_float(_get_value(item, "city_avg_psh", "overall_avg_psh"))

            result.append(
                {
                    "plant_name": _get_value(item, "plant_name", "Plant Name"),
                    "city": _get_value(item, "city", "City"),
                    "status": _get_value(item, "status", "plant_status", default="Unknown"),
                    "psh": psh,
                    "city_avg_psh": city_avg_psh,
                    "threshold_psh": _safe_float(_get_value(item, "threshold_psh")),
                    "deviation_pct": _safe_deviation_pct(
                        psh,
                        city_avg_psh,
                        _get_value(
                            item,
                            "psh_deviation_pct_vs_city_avg",
                            "psh_deviation_pct",
                            "deviation_pct",
                        ),
                    ),
                    "performance_status": _get_value(item, "performance_status"),
                    "underperforming": bool(_get_value(item, "underperforming", default=False)),
                    "run_day": run_day,
                }
            )

        return result

    except Exception:
        db.rollback()
        return []

def _fetch_active_alarms(db: Session) -> list[dict]:
    try:
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
                    ORDER BY plant_name ASC
                    """
                )
            )
            .mappings()
            .all()
        )

        return [
            {
                "plant_name": row["plant_name"],
                "device_name": row["device_name"],
                "device_sn": row["device_sn"],
                "alarm_name": row["alarm_name"],
                "severity": row["severity"],
                "occurrence_ts": row["occurrence_ts"],
            }
            for row in rows
        ]

    except Exception:
        db.rollback()
        return []

def _fetch_high_temperature_inverters(
    db: Session,
    *,
    run_day: date | None,
) -> list[dict]:
    if run_day is None:
        return []

    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT *
                    FROM high_temperature_inverters_latest
                    WHERE run_day = :run_day
                    ORDER BY plant_name ASC
                    """
                ),
                {"run_day": run_day},
            )
            .mappings()
            .all()
        )

        result: list[dict] = []

        for row in rows:
            item = dict(row)

            result.append(
                {
                    "plant_name": _get_value(item, "plant_name"),
                    "device_name": _get_value(item, "device_name", "inverter_name"),
                    "device_sn": _get_value(item, "device_sn", "inverter_sn"),
                    "internal_temperature_c": _safe_float(
                        _get_value(item, "internal_temperature_c", "temperature_c")
                    ),
                    "run_day": run_day,
                }
            )

        return result

    except Exception:
        db.rollback()
        return []

    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT
                        job_name,
                        status,
                        started_at,
                        finished_at,
                        details
                    FROM job_runs
                    ORDER BY started_at DESC NULLS LAST
                    LIMIT 10
                    """
                )
            )
            .mappings()
            .all()
        )

        return [
            {
                "job_name": row["job_name"],
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "details": row["details"],
            }
            for row in rows
        ]

    except Exception:
        db.rollback()
        return []

@router.get("/overview")
def dashboard_overview(db: Session = Depends(get_db)):
    dashboard_day = today_gmt8()

    low_psh_run_day = _get_latest_low_psh_run_day(db)
    high_temperature_run_day = _get_latest_high_temperature_run_day(db)

    low_performing_plants = _fetch_low_performing_plants(
        db,
        run_day=low_psh_run_day,
    )

    active_alarms = _fetch_active_alarms(db)

    high_temperature_inverters = _fetch_high_temperature_inverters(
        db,
        run_day=high_temperature_run_day,
    )

    response = {
        "dashboard_day": dashboard_day,
        "report_day": low_psh_run_day or dashboard_day,
        "data_days": {
            "low_psh_plants": low_psh_run_day,
            "high_temperature_inverters": high_temperature_run_day,
        },
        "kpis": {
            "low_performing_plants": len(low_performing_plants),
            "active_alarms": len(active_alarms),
            "high_temperature_inverters": len(high_temperature_inverters),
        },
        "low_performing_plants": low_performing_plants,
        "active_alarms": active_alarms,
        "high_temperature_inverters": high_temperature_inverters,
    }

    return _json_safe(response)