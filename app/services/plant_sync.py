from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy.orm import Session
from app.db.models.plant import Plant

def parse_decimal(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text or text == "--":
        return None

    cleaned = (
        text.replace(",", "")
        .replace("kWh/kWp", "")
        .replace("kWh", "")
        .replace("kWp", "")
        .replace("kW", "")
        .strip()
    )

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    
def safe_get(row, index, default=None):
    return row[index] if index < len(row) else default

def parse_date(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text or text == "--":
        return None

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None

def clean_row(row):
    print(f"DEBUG row length = {len(row)} | row = {row}")

    return {
        "status": safe_get(row, 0),
        "name": safe_get(row, 2),
        "country": safe_get(row, 3),
        "grid_connection_date": parse_date(safe_get(row, 4)),
        "total_string_capacity_kwp": parse_decimal(safe_get(row, 5)),
        "current_power_kw": parse_decimal(safe_get(row, 8)),
        "specific_energy_kwh_kwp": parse_decimal(safe_get(row, 9)),
        "yield_today_kwh": parse_decimal(safe_get(row, 10)),
        "total_yield_kwh": parse_decimal(safe_get(row, 11)),
    }

def sync_plants_from_dom(db: Session, rows: list[list[str]]):
    for raw_row in rows:
        data = clean_row(raw_row)

        existing = db.query(Plant).filter(Plant.name == data["name"]).first()

        if existing:
            existing.status = data["status"]
            existing.country = data["country"]
            existing.grid_connection_date = data["grid_connection_date"]
            existing.total_string_capacity_kwp = data["total_string_capacity_kwp"]
            existing.current_power_kw = data["current_power_kw"]
            existing.specific_energy_kwh_kwp = data["specific_energy_kwh_kwp"]
            existing.yield_today_kwh = data["yield_today_kwh"]
            existing.total_yield_kwh = data["total_yield_kwh"]

            print(f"Updated plant: {data['name']}")
        else:
            plant = Plant(**data)
            db.add(plant)
            print(f"Inserted plant: {data['name']}")
    db.commit()        