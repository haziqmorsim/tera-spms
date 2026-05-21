from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime

from app.db.deps import get_db
from app.db.models.inverter_sample import InverterSample5m
from app.db.models.inverter import Inverter

router = APIRouter()


@router.get("/inverters/{inverter_id}/timeseries")
def inverter_timeseries(
    inverter_id: str,
    from_ts: str = Query(..., description="ISO timestamp"),
    to_ts: str = Query(..., description="ISO timestamp"),
    limit: int = Query(default=2000, le=5000),
    db: Session = Depends(get_db),
):
    inv = db.get(Inverter, inverter_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inverter not found")

    start = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    end = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))

    q = (
        select(InverterSample5m)
        .where(InverterSample5m.inverter_id == inv.id)
        .where(InverterSample5m.ts >= start, InverterSample5m.ts <= end)
        .order_by(InverterSample5m.ts.asc())
        .limit(limit)
    )
    rows = db.execute(q).scalars().all()

    return {
        "inverter_id": inverter_id,
        "from": start.format_datetime_gmt8(),
        "to": end.format_datetime_gmt8(),
        "points": [
            {
                "ts": r.ts.format_datetime_gmt8(),
                "status": r.status,
                "ac_power_w": float(r.ac_power_w) if r.ac_power_w is not None else None,
                "energy_kwh": float(r.energy_kwh) if r.energy_kwh is not None else None,
                "pv_string_currents": r.pv_string_currents,
            }
            for r in rows
        ],
    }
