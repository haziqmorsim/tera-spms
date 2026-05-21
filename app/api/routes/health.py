from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.deps import get_db

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/telemetry")
def telemetry_health(db: Session = Depends(get_db)):
    freshness = db.execute(text("""
        SELECT
          COUNT(*) AS devices_total,
          COUNT(*) FILTER (WHERE last_telemetry_ts >= now() - interval '10 minutes') AS devices_fresh_10m,
          COUNT(*) FILTER (WHERE last_telemetry_ts <  now() - interval '30 minutes' OR last_telemetry_ts IS NULL) AS devices_stale_30m
        FROM inverters;
    """)).fetchone()

    last_run = db.execute(text("""
        SELECT started_at, finished_at, ok_count, fail_count
        FROM sync_runs
        WHERE job_name = 'telemetry_5m'
        ORDER BY started_at DESC
        LIMIT 1;
    """)).fetchone()

    return {
        "devices": {
            "total": int(freshness[0]),
            "fresh_10m": int(freshness[1]),
            "stale_30m": int(freshness[2]),
        },
        "last_run": None if not last_run else {
            "started_at": last_run[0],
            "finished_at": last_run[1],
            "ok": int(last_run[2]),
            "fail": int(last_run[3]),
        }
    }