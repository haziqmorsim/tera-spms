from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from datetime import datetime, timezone

from app.db.deps import get_db
from app.db.models.plant import Plant
from app.db.models.inverter import Inverter
from app.db.models.alarm import Alarm
from app.utils.time_utils import format_date_ddmmyyyy, format_datetime_gmt8, now_gmt8

router = APIRouter()


@router.get("")
def list_plants(db: Session = Depends(get_db)):
    plants = db.execute(select(Plant).order_by(Plant.name)).scalars().all()
    return [
        {
            "id": str(p.id),
            "status": p.status,
            "name": p.name,
            "country": p.country,
            "grid_connection_date": format_date_ddmmyyyy(p.grid_connection_date),
            "total_string_capacity_kwp": (
                float(p.total_string_capacity_kwp)
                if p.total_string_capacity_kwp is not None
                else None
            ),
            "current_power_kw": (
                float(p.current_power_kw) if p.current_power_kw is not None else None
            ),
            "specific_energy_kwh_kwp": (
                float(p.specific_energy_kwh_kwp)
                if p.specific_energy_kwh_kwp is not None
                else None
            ),
            "yield_today_kwh": (
                float(p.yield_today_kwh) if p.yield_today_kwh is not None else None
            ),
            "total_yield_kwh": (
                float(p.total_yield_kwh) if p.total_yield_kwh is not None else None
            ),
        }
        for p in plants
    ]


@router.get("/{plant_id}")
def get_plant(plant_id: str, db: Session = Depends(get_db)):
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return [
        {
            "id": str(p.id),
            "status": p.status,
            "name": p.name,
            "country": p.country,
            "grid_connection_date": format_date_ddmmyyyy(p.grid_connection_date),
            "total_string_capacity_kwp": (
                float(p.total_string_capacity_kwp)
                if p.total_string_capacity_kwp is not None
                else None
            ),
            "current_power_kw": (
                float(p.current_power_kw) if p.current_power_kw is not None else None
            ),
            "specific_energy_kwh_kwp": (
                float(p.specific_energy_kwh_kwp)
                if p.specific_energy_kwh_kwp is not None
                else None
            ),
            "yield_today_kwh": (
                float(p.yield_today_kwh) if p.yield_today_kwh is not None else None
            ),
            "total_yield_kwh": (
                float(p.total_yield_kwh) if p.total_yield_kwh is not None else None
            ),
        }
        for p in plant
    ]


@router.get("/{plant_id}/summary")
def plant_summary(plant_id: str, db: Session = Depends(get_db)):
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    # Status counts from inverters table (simple version for now)
    inv_rows = db.execute(
        select(Inverter.last_status, func.count())
        .where(Inverter.plant_id == plant.id, Inverter.is_active == True)
        .group_by(Inverter.last_status)
    ).all()

    status_counts = {(s or "unknown"): c for (s, c) in inv_rows}

    # Active alarms donut (by severity)
    alarm_rows = db.execute(
        select(Alarm.severity, func.count())
        .where(Alarm.plant_id == plant.id, Alarm.is_active == True)
        .group_by(Alarm.severity)
    ).all()
    alarm_counts = {(sev or "unknown"): c for (sev, c) in alarm_rows}

    return {
        "plant": {
            "id": str(plant.id),
            "status": plant.status,
            "name": plant.name,
            "country": plant.country,
            "grid_connection_date": format_date_ddmmyyyy(plant.grid_connection_date),
            "total_string_capacity_kwp": (
                float(plant.total_string_capacity_kwp)
                if plant.total_string_capacity_kwp is not None
                else None
            ),
            "current_power_kw": (
                float(plant.current_power_kw)
                if plant.current_power_kw is not None
                else None
            ),
            "specific_energy_kwh_kwp": (
                float(plant.specific_energy_kwh_kwp)
                if plant.specific_energy_kwh_kwp is not None
                else None
            ),
            "yield_today_kwh": (
                float(plant.yield_today_kwh)
                if plant.yield_today_kwh is not None
                else None
            ),
            "total_yield_kwh": (
                float(plant.total_yield_kwh)
                if plant.total_yield_kwh is not None
                else None
            ),
        },
        "plant_status_counts": status_counts,  # Normal/Faulty/Disconnected later
        "active_alarm_counts": alarm_counts,  # critical/major/minor/warning
        "generated_at": format_datetime_gmt8(now_gmt8()),
    }
