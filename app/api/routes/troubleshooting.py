from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db
from app.services.troubleshooting_service import (
    fetch_troubleshoot_dataset,
    analyse_problem_vs_normal,
    build_comparison_outputs,
    save_troubleshooting_run,
)

router = APIRouter(prefix="/troubleshoot", tags=["Troubleshooting"])


@router.get("/{device_sn}")
def troubleshoot_inverter(
    device_sn: str,
    minutes: int = Query(120, ge=30, le=1440),
    save: bool = Query(False),
    created_by: str | None = Query(None),
    notes: str | None = Query(None),
    db: Session = Depends(get_db),
):

    try:
        dateset = fetch_troubleshoot_dataset(
            db,
            problem_sn=device_sn,
            window_minutes=minutes,
        )
        result = analyse_problem_vs_normal(dateset)
        result["outputs"] = build_comparison_outputs(result)

        # Ensure device_sn is present in payload for persistence/audit
        if "problem_inverter" in result and isinstance(
            result["problem_inverter"], dict
        ):
            result["problem_inverter"].setdefault("device_sn", device_sn)

        if save:
            run_id = save_troubleshooting_run(
                db, result, created_by=created_by or "system", notes=notes
            )
            result["run_id"] = run_id

        return result

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{device_sn}/runs")
def list_runs(
    device_sn: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.execute(
            text(
                """
            SELECT
              id,
              created_at,
              device_sn,
              plant_name,
              model,
              window_start,
              window_end,
              classification,
              severity,
              median_power_ratio,
              median_temp_c,
              baseline_type,
              peer_count,
              created_by
            FROM troubleshooting_runs
            WHERE device_sn = :sn
            ORDER BY created_at DESC
            LIMIT :limit
        """
            ),
            {"sn": device_sn, "limit": limit},
        )
        .mappings()
        .all()
    )

    return list(rows)


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
):
    row = (
        db.execute(
            text(
                """
            SELECT
              r.id,
              r.created_at,
              r.device_sn,
              r.plant_name,
              r.model,
              r.window_start,
              r.window_end,
              r.classification,
              r.severity,
              r.median_power_ratio,
              r.median_temp_c,
              r.baseline_type,
              r.peer_count,
              r.created_by,
              r.notes,
              d.payload
            FROM troubleshooting_runs r
            JOIN troubleshooting_run_data d
              ON d.run_id = r.id
            WHERE r.id = :id
        """
            ),
            {"id": run_id},
        )
        .mappings()
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    return dict(row)
