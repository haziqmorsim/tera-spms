from decimal import Decimal
from sqlalchemy.orm import Session
from app.db.models.inverter import Inverter
from datetime import datetime, timezone

def parse_decimal(v: str):
    if not v or v == "--":
        return None
    return Decimal(v.replace(",", ""))

def clean_inverter_row(row: list[str]) -> dict:
    return {
        "device_status": row[0],
        "device_name": row[2],
        "plant_name": row[3],
        "device_type": row[4],        
        "software_version": row[5],
        "device_sn": row[6],
        "superior_equipment": row[7] or None,
        "communication_device": (row[8] or row[9]) if len(row) > 9 else (row[8] if len(row) > 8 else None),
        "model": row[10] if len(row) > 10 else None,
    }

def upsert_inverters_global(db: Session, rows: list[list[str]]):
    for r in rows:
        data = clean_inverter_row(r)
        now = datetime.now(timezone.utc)

        existing = (
            db.query(Inverter)
            .filter(Inverter.plant_name == data["plant_name"], Inverter.device_sn == data["device_sn"])
            .first()
        )

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
                existing.last_seen_ts = now
        else:
            db.add(Inverter(**data, last_seen_ts=now))

    db.commit()