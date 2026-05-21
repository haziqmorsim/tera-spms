from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session

TELEMETRY_COLS = [
    "inverter_status",
    "active_power_kw",
    "daily_energy_kwh",
    "total_yield_kwh",
    "grid_frequency_hz",
    "internal_temperature_c",
    "power_factor",
    "reactive_power_kvar",
    "grid_phase_a_current_a",
    "grid_phase_b_current_a",
    "grid_phase_c_current_a",
    "phase_a_voltage_v",
    "phase_b_voltage_v",
    "phase_c_voltage_v",
    "insulation_resistance_mohm",
    "pv1_voltage_v",
    "pv1_current_a",
    "pv2_voltage_v",
    "pv2_current_a",
    "pv3_voltage_v",
    "pv3_current_a",
    "pv4_voltage_v",
    "pv4_current_a",
]

def align_to_5min_window(dt: datetime | None = None) -> datetime:
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    minute = (dt.minute // 5) * 5
    return dt.replace(minute=minute, second=0, microsecond=0)

def upsert_telemetry_5m(
    db: Session,
    *,
    device_sn: str,
    plant_name: str | None,
    telemetry: dict,
) -> datetime:
    ts = align_to_5min_window()

    payload = {
        "ts": ts,
        "device_sn": device_sn,
        "plant_name": plant_name,
    }

    for k in TELEMETRY_COLS:
        payload[k] = telemetry.get(k)

    cols = ", ".join(payload.keys())
    params = ", ".join([f":{k}" for k in payload.keys()])
    set_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in payload.keys() if k not in ("ts", "device_sn")])

    sql = text(f"""
        INSERT INTO inverter_telemetry_5m ({cols})
        VALUES ({params})
        ON CONFLICT (device_sn, ts)
        DO UPDATE SET {set_clause};
    """)

    db.execute(sql, payload)

    db.execute(
        text("UPDATE inverters SET last_seen_ts = :now WHERE device_sn = :sn"),
        {"now": datetime.now(timezone.utc), "sn": device_sn},
    )

    db.execute(
        text("UPDATE inverters SET last_telemetry_ts = :ts WHERE device_sn = :sn"),
        {"ts": ts, "sn": device_sn},
    )

    db.commit()
    return ts