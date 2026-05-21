from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.utils.time_utils import format_date_ddmmyyyy, format_datetime_gmt8

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMP_THRESHOLD_C = float(os.getenv("TEMP_THRESHOLD_C", "70"))


@router.get("/overview")
def dashboard_overview(db: Session = Depends(get_db)):
    try:
        low_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        run_day,
                        plant_name,
                        city,
                        psh,
                        city_avg_psh,
                        threshold_psh,
                        psh_deviation_pct_vs_city_avg
                    FROM low_psh_plants_by_city_latest
                    WHERE run_day = (
                        SELECT MAX(run_day)
                        FROM low_psh_plants_by_city_latest
                    )
                      AND underperforming = true
                    ORDER BY plant_name ASC
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        low_rows = []

    low_performing_plants = [
        {
            "day": format_date_ddmmyyyy(r["run_day"]) if r["run_day"] is not None else None,
            "plant_name": r["plant_name"],
            "city": r["city"],
            "plant_avg_psh": float(r["psh"]) if r["psh"] is not None else None,
            "overall_avg_psh": float(r["city_avg_psh"]) if r["city_avg_psh"] is not None else None,
            "low_psh_threshold": float(r["threshold_psh"]) if r["threshold_psh"] is not None else None,
            "psh_deviation_pct": (
                float(r["psh_deviation_pct_vs_city_avg"])
                if r["psh_deviation_pct_vs_city_avg"] is not None
                else None
            ),
        }
        for r in low_rows
    ]

    try:
        alarm_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
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
    except Exception:
        db.rollback()
        alarm_rows = []

    alarms = [
        {
            "id": str(r["id"]) if r["id"] is not None else None,
            "plant_name": r["plant_name"],
            "device_name": r["device_name"],
            "device_sn": r["device_sn"],
            "alarm_name": r["alarm_name"],
            "severity": r["severity"],
            "occurrence_ts": (
                format_datetime_gmt8(r["occurrence_ts"]) if r["occurrence_ts"] else None
            ),
        }
        for r in alarm_rows
    ]

    try:
        temp_rows = (
            db.execute(
                text(
                    """
                    SELECT
                        run_day,
                        plant_name,
                        device_name,
                        device_sn,
                        internal_temperature_c,
                        source_ts
                    FROM high_temperature_inverters_latest
                    WHERE run_day = (
                        SELECT MAX(run_day)
                        FROM high_temperature_inverters_latest
                    )
                    ORDER BY plant_name ASC, device_name ASC
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        db.rollback()
        temp_rows = []

    high_temperature_inverters = [
        {
            "day": format_date_ddmmyyyy(r["run_day"]) if r["run_day"] is not None else None,
            "plant_name": r["plant_name"],
            "device_name": r["device_name"],
            "device_sn": r["device_sn"],
            "ts": format_datetime_gmt8(r["source_ts"]) if r["source_ts"] else None,
            "internal_temperature_c": (
                float(r["internal_temperature_c"])
                if r["internal_temperature_c"] is not None
                else None
            ),
        }
        for r in temp_rows
    ]

    return {
        "summary": {
            "low_performing_plant_count": len(low_performing_plants),
            "active_alarm_count": len(alarms),
            "high_temperature_inverter_count": len(high_temperature_inverters),
            "temperature_threshold_c": TEMP_THRESHOLD_C,
        },
        "low_performing_plants": low_performing_plants,
        "alarms": alarms,
        "high_temperature_inverters": high_temperature_inverters,
    }