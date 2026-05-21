from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.deps import get_db
from app.db.models.inverter import Inverter
from app.utils.time_utils import format_datetime_gmt8

router = APIRouter()


@router.get("")
def list_inverters(
    plant_id: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    q = select(Inverter)
    if plant_id:
        q = q.where(Inverter.plant_id == plant_id)
    if active_only:
        q = q.where(Inverter.is_active == True)

    inverters = db.execute(q.order_by(Inverter.device_name)).scalars().all()
    return [
        {
            "id": str(i.id),
            "plant_id": str(i.plant_id),
            "brand": i.brand,
            "device_sn": i.device_sn,
            "device_name": i.device_name,
            "model": i.model,
            "is_active": i.is_active,
            "last_seen_ts": (
                format_datetime_gmt8(i.last_seen_ts) if i.last_seen_ts else None
            ),
            "last_status": i.last_status,
        }
        for i in inverters
    ]


@router.get("/{inverter_id}")
def get_inverter(inverter_id: str, db: Session = Depends(get_db)):
    inv = db.get(Inverter, inverter_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inverter not found")
    return {
        "id": str(inv.id),
        "plant_id": str(inv.plant_id),
        "brand": inv.brand,
        "device_sn": inv.device_sn,
        "device_name": inv.device_name,
        "model": inv.model,
        "is_active": inv.is_active,
        "last_seen_ts": (
            format_datetime_gmt8(inv.last_seen_ts) if inv.last_seen_ts else None
        ),
        "last_status": inv.last_status,
    }
