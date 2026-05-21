from __future__ import annotations
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class BaselineResult:
    baseline_type: str
    peer_sns: List[str]


def _to_float(x):
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def _median_non_null(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    return median(clean) if clean else None


def _pick_peers(
    db: Session,
    *,
    plant_name: str,
    model: Optional[str],
    t_start: datetime,
    t_end: datetime,
    min_peers: int = 3,
) -> BaselineResult:

    def run_peer_query(sql: str, params: Dict[str, Any]) -> List[str]:
        rows = db.execute(text(sql), params).fetchall()
        return [r[0] for r in rows if r and r[0]]

    if model:
        peers = run_peer_query(
            """
            SELECT i.device_sn
            FROM inverters i
            WHERE i.plant_name = :plant_name
              AND i.model = :model
              AND i.device_status = 'Normal'
              AND NOT EXISTS (
                SELECT 1 FROM issues iss
                WHERE iss.device_sn = i.device_sn
                  AND iss.status IN ('OPEN', 'IN_PROGRESS')
              )
              AND EXISTS (
                SELECT 1
                FROM inverter_telemetry_5m t
                WHERE t.device_sn = i.device_sn
                  AND t.ts >= :t_start
                  AND t.ts < :t_end
              )
            """,
            {
                "plant_name": plant_name,
                "model": model,
                "t_start": t_start,
                "t_end": t_end,
            },
        )
        if len(peers) >= min_peers:
            return BaselineResult("PLANT_MODEL", peers)

    peers = run_peer_query(
        """
        SELECT i.device_sn
        FROM inverters i
        WHERE i.plant_name = :plant_name
          AND i.device_status = 'Normal'
          AND NOT EXISTS (
            SELECT 1 FROM issues iss
            WHERE iss.device_sn = i.device_sn
              AND iss.status IN ('OPEN', 'IN_PROGRESS')
          )
          AND EXISTS (
            SELECT 1
            FROM inverter_telemetry_5m t
            WHERE t.device_sn = i.device_sn
              AND t.ts >= :t_start
              AND t.ts < :t_end
          )
        """,
        {
            "plant_name": plant_name,
            "t_start": t_start,
            "t_end": t_end,
        },
    )
    if len(peers) >= min_peers:
        return BaselineResult("PLANT_ANY", peers)

    if model:
        peers = run_peer_query(
            """
            SELECT i.device_sn
            FROM inverters i
            WHERE i.model = :model
              AND i.device_status = 'Normal'
              AND NOT EXISTS (
                SELECT 1 FROM issues iss
                WHERE iss.device_sn = i.device_sn
                  AND iss.status IN ('OPEN', 'IN_PROGRESS')
              )
              AND EXISTS (
                SELECT 1
                FROM inverter_telemetry_5m t
                WHERE t.device_sn = i.device_sn
                  AND t.ts >= :t_start
                  AND t.ts < :t_end
              )
            """,
            {
                "model": model,
                "t_start": t_start,
                "t_end": t_end,
            },
        )
        if len(peers) >= min_peers:
            return BaselineResult("MODEL_GLOBAL", peers)

    return BaselineResult("SELF", [])


def fetch_troubleshoot_dataset(
    db: Session,
    *,
    problem_sn: str,
    window_minutes: int = 120,
    min_peers: int = 3,
) -> Dict[str, Any]:

    inv = (
        db.execute(
            text(
                """
            SELECT plant_name, model, device_name, device_status
            FROM inverters
            WHERE device_sn = :sn
            LIMIT 1
            """
            ),
            {"sn": problem_sn},
        )
        .mappings()
        .first()
    )

    if not inv:
        raise RuntimeError(f"Inverter not found in DB: {problem_sn}")

    plant_name: str = inv["plant_name"]
    model: Optional[str] = inv.get("model")

    t_end = datetime.now(timezone.utc)
    t_start = t_end - timedelta(minutes=window_minutes)

    problem_series = (
        db.execute(
            text(
                """
            SELECT
              time_bucket('5 minutes', ts) AS bucket,
              AVG(active_power_kw) AS active_power_kw,
              MAX(daily_energy_kwh) AS daily_energy_kwh,
              MAX(total_yield_kwh) AS total_yield_kwh,
              AVG(internal_temperature_c) AS internal_temperature_c,
              AVG(grid_frequency_hz) AS grid_frequency_hz,
              AVG(power_factor) AS power_factor,
              AVG(reactive_power_kvar) AS reactive_power_kvar,
              AVG(grid_phase_a_current_a) AS grid_phase_a_current_a,
              AVG(grid_phase_b_current_a) AS grid_phase_b_current_a,
              AVG(grid_phase_c_current_a) AS grid_phase_c_current_a,
              AVG(phase_a_voltage_v) AS phase_a_voltage_v,
              AVG(phase_b_voltage_v) AS phase_b_voltage_v,
              AVG(phase_c_voltage_v) AS phase_c_voltage_v,
              AVG(insulation_resistance_mohm) AS insulation_resistance_mohm
            FROM inverter_telemetry_5m
            WHERE device_sn = :sn
              AND ts >= :t_start AND ts < :t_end
            GROUP BY bucket
            ORDER BY bucket
            """
            ),
            {"sn": problem_sn, "t_start": t_start, "t_end": t_end},
        )
        .mappings()
        .all()
    )

    baseline = _pick_peers(
        db,
        plant_name=plant_name,
        model=model,
        t_start=t_start,
        t_end=t_end,
        min_peers=min_peers,
    )

    baseline_series: List[Dict[str, Any]] = []
    baseline_pv_snapshot: Optional[Dict[str, Any]] = None

    if baseline.baseline_type != "SELF" and baseline.peer_sns:
        baseline_series = (
            db.execute(
                text(
                    """
                WITH peer_series AS (
                  SELECT
                    time_bucket('5 minutes', t.ts) AS bucket,
                    t.device_sn,
                    AVG(t.active_power_kw) AS p_kw
                  FROM inverter_telemetry_5m t
                  WHERE t.device_sn = ANY(:peer_sns)
                    AND t.ts >= :t_start AND t.ts < :t_end
                  GROUP BY bucket, t.device_sn
                )
                SELECT
                  bucket,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY p_kw) AS baseline_power_kw
                FROM peer_series
                GROUP BY bucket
                ORDER BY bucket
                """
                ),
                {"peer_sns": baseline.peer_sns, "t_start": t_start, "t_end": t_end},
            )
            .mappings()
            .all()
        )

        baseline_pv_snapshot = (
            db.execute(
                text(
                    """
                WITH latest_peer AS (
                  SELECT DISTINCT ON (device_sn)
                    device_sn, ts,
                    pv1_voltage_v, pv1_current_a,
                    pv2_voltage_v, pv2_current_a,
                    pv3_voltage_v, pv3_current_a,
                    pv4_voltage_v, pv4_current_a
                  FROM inverter_telemetry_5m
                  WHERE device_sn = ANY(:peer_sns)
                    AND ts >= :t_start AND ts < :t_end
                  ORDER BY device_sn, ts DESC
                )
                SELECT
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv1_voltage_v) AS pv1_voltage_v_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv1_current_a) AS pv1_current_a_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv2_voltage_v) AS pv2_voltage_v_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv2_current_a) AS pv2_current_a_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv3_voltage_v) AS pv3_voltage_v_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv3_current_a) AS pv3_current_a_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv4_voltage_v) AS pv4_voltage_v_med,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY pv4_current_a) AS pv4_current_a_med
                FROM latest_peer
                """
                ),
                {"peer_sns": baseline.peer_sns, "t_start": t_start, "t_end": t_end},
            )
            .mappings()
            .first()
        )
        baseline_pv_snapshot = (
            dict(baseline_pv_snapshot) if baseline_pv_snapshot else None
        )

    pv_latest = (
        db.execute(
            text(
                """
            SELECT
              ts,
              pv1_voltage_v, pv1_current_a,
              pv2_voltage_v, pv2_current_a,
              pv3_voltage_v, pv3_current_a,
              pv4_voltage_v, pv4_current_a
            FROM inverter_telemetry_5m
            WHERE device_sn = :sn
              AND ts >= :t_start AND ts < :t_end
            ORDER BY ts DESC
            LIMIT 1
            """
            ),
            {"sn": problem_sn, "t_start": t_start, "t_end": t_end},
        )
        .mappings()
        .first()
    )

    active_alarms = (
        db.execute(
            text(
                """
            SELECT alarm_id, alarm_name, severity, occurrence_ts
            FROM alarms
            WHERE device_sn = :sn
              AND is_active = true
            ORDER BY occurrence_ts DESC
            LIMIT 20
            """
            ),
            {"sn": problem_sn},
        )
        .mappings()
        .all()
    )

    return {
        "problem_inverter": {
            **dict(inv),
            "device_sn": problem_sn,
        },
        "window": {
            "start": t_start.isoformat(),
            "end": t_end.isoformat(),
            "minutes": window_minutes,
        },
        "baseline": {
            "type": baseline.baseline_type,
            "peer_count": len(baseline.peer_sns),
            "peer_sns_preview": baseline.peer_sns[:50],
        },
        "problem_series": list(problem_series),
        "baseline_series": list(baseline_series),
        "pv_latest": dict(pv_latest) if pv_latest else None,
        "baseline_pv_snapshot": baseline_pv_snapshot,
        "active_alarms": [dict(r) for r in active_alarms],
    }


def analyse_problem_vs_normal(payload: dict) -> dict:
    """
    Criteria-aligned classifier:
      C1 SHADING_LOSS
      C2 SELF_DERATING
      C3 ABNORMAL_OUTPUT
      C4 PV_STRING_MISSING
      C5 LOW_CURRENT_GENERATION
      C6 SOILING
      C7 ALARM
      C8 TEMPERATURE_HIGH
    """
    problem_series = payload.get("problem_series") or []
    baseline_series = payload.get("baseline_series") or []
    pv_latest = payload.get("pv_latest") or None
    active_alarms = payload.get("active_alarms") or []

    baseline_map = {
        r.get("bucket"): _to_float(r.get("baseline_power_kw")) for r in baseline_series
    }

    ratio_series = []
    ratios = []
    temps = []

    for r in problem_series:
        b = r.get("bucket")
        p_kw = _to_float(r.get("active_power_kw"))
        base_kw = baseline_map.get(b)

        ratio = None
        if p_kw is not None and base_kw is not None and base_kw > 0:
            ratio = p_kw / base_kw
            ratios.append(ratio)

        t = _to_float(r.get("internal_temperature_c"))
        if t is not None:
            temps.append(t)

        ratio_series.append(
            {
                "bucket": b,
                "problem_power_kw": p_kw,
                "baseline_power_kw": base_kw,
                "power_ratio": ratio,
                "temp_c": t,
            }
        )

    ratio_med = _median_non_null(ratios)
    ratio_std = statistics.pstdev(ratios) if len(ratios) >= 2 else None
    ratio_min = min(ratios) if ratios else None
    ratio_max = max(ratios) if ratios else None

    temp_max = max(temps) if temps else None
    temp_med = _median_non_null(temps)

    pv_missing = []
    pv_low_current = []

    if pv_latest:
        currents = [
            _to_float(pv_latest.get("pv1_current_a")),
            _to_float(pv_latest.get("pv2_current_a")),
            _to_float(pv_latest.get("pv3_current_a")),
            _to_float(pv_latest.get("pv4_current_a")),
        ]
        med_i = _median_non_null(currents)
        max_i = max([i for i in currents if i is not None] or [0.0])
        daylight = max_i >= 0.8

        if daylight and med_i is not None and med_i > 0:
            for idx, cur in enumerate(currents, start=1):
                if cur is None:
                    continue

                if cur <= 0.05 and max_i >= 0.8:
                    pv_missing.append({"pv": f"PV{idx}", "current_a": cur})

                if cur > 0.05 and cur < 0.50 * med_i:
                    pv_low_current.append(
                        {
                            "pv": f"PV{idx}",
                            "current_a": cur,
                            "median_current_a": med_i,
                        }
                    )

    if temp_max is not None and temp_max >= 70.0:
        classification = "TEMPERATURE_HIGH"
        severity = "MAJOR" if temp_max < 80.0 else "CRITICAL"
        reason = f"Internal temperature reached {temp_max:.1f}°C (>=70°C)."

    elif active_alarms:
        classification = "ALARM"
        sev_rank = {"critical": 3, "major": 2, "minor": 1, "warning": 0}
        best = 1
        for a in active_alarms:
            best = max(best, sev_rank.get((a.get("severity") or "").lower(), 1))
        severity = {3: "CRITICAL", 2: "MAJOR", 1: "MINOR", 0: "INFO"}[best]
        reason = (
            f"Active FusionSolar alarm detected: {active_alarms[0].get('alarm_name')}"
        )

    elif pv_missing:
        classification = "PV_STRING_MISSING"
        severity = "MAJOR"
        reason = "PV string current is near-zero while other strings are producing."

    else:
        if ratio_med is None:
            classification = "NORMAL"
            severity = "INFO"
            reason = "Insufficient baseline data to compute ratios."
        else:
            if temp_med is not None and temp_med >= 60.0 and ratio_med < 0.85:
                classification = "SELF_DERATING"
                severity = "MAJOR" if ratio_med < 0.70 else "MINOR"
                reason = "High temperature with suppressed power ratio suggests self-derating."

            elif ratio_std is not None and ratio_med < 0.90 and ratio_std <= 0.05:
                classification = "SOILING"
                severity = "MINOR" if ratio_med >= 0.75 else "MAJOR"
                reason = "Consistent low ratio with low variance suggests soiling."

            elif ratio_std is not None and ratio_med < 0.95 and ratio_std >= 0.15:
                classification = "SHADING_LOSS"
                severity = "MINOR" if ratio_med >= 0.80 else "MAJOR"
                reason = "High ratio variance suggests shading loss."

            elif pv_low_current:
                classification = "LOW_CURRENT_GENERATION"
                severity = "MINOR"
                reason = "One or more PV strings show significantly lower current than peers."

            elif ratio_med < 0.70:
                classification = "ABNORMAL_OUTPUT"
                severity = "MAJOR" if ratio_med >= 0.50 else "CRITICAL"
                reason = "Median power ratio is significantly below baseline peers."

            else:
                classification = "NORMAL"
                severity = "INFO"
                reason = "No criteria threshold breached."

    kpis = {
        "median_power_ratio": ratio_med,
        "min_power_ratio": ratio_min,
        "max_power_ratio": ratio_max,
        "std_power_ratio": ratio_std,
        "median_temp_c": temp_med,
        "max_temp_c": temp_max,
        "pv_missing": pv_missing,
        "pv_low_current": pv_low_current,
        "active_alarm_count": len(active_alarms),
        "criteria_reason": reason,
    }

    return {
        "classification": classification,
        "severity": severity,
        "kpis": kpis,
        "series": ratio_series,
        "pv_latest": pv_latest,
        "baseline": payload.get("baseline"),
        "window": payload.get("window"),
        "problem_inverter": payload.get("problem_inverter"),
        "active_alarms": active_alarms,
    }


def build_comparison_outputs(result: dict) -> dict:
    series = result.get("series", [])
    pv = result.get("pv_latest") or {}

    power_lines = {
        "ts": [r["bucket"] for r in series],
        "problem_power_kw": [r["problem_power_kw"] for r in series],
        "baseline_power_kw": [r["baseline_power_kw"] for r in series],
    }

    ratio_line = {
        "ts": [r["bucket"] for r in series],
        "power_ratio": [r["power_ratio"] for r in series],
    }

    missing_pvs = set(d["pv"] for d in (result["kpis"].get("pv_missing") or []))
    low_pvs = set(d["pv"] for d in (result["kpis"].get("pv_low_current") or []))

    pv_rows = []
    for i in range(1, 5):
        pv_name = f"PV{i}"
        flag = ""
        if pv_name in missing_pvs:
            flag = "MISSING"
        elif pv_name in low_pvs:
            flag = "LOW_CURRENT"

        pv_rows.append(
            {
                "pv": pv_name,
                "voltage_v": pv.get(f"pv{i}_voltage_v"),
                "current_a": pv.get(f"pv{i}_current_a"),
                "flag": flag,
            }
        )

    summary = [
        {"metric": "Classification", "value": result.get("classification")},
        {"metric": "Severity", "value": result.get("severity")},
        {
            "metric": "Median Power Ratio",
            "value": result["kpis"].get("median_power_ratio"),
        },
        {
            "metric": "Median Temperature (°C)",
            "value": result["kpis"].get("median_temp_c"),
        },
        {"metric": "Max Temperature (°C)", "value": result["kpis"].get("max_temp_c")},
        {
            "metric": "Active Alarm Count",
            "value": result["kpis"].get("active_alarm_count"),
        },
        {"metric": "Reason", "value": result["kpis"].get("criteria_reason")},
    ]

    return {
        "charts": {
            "power_lines": power_lines,
            "ratio_line": ratio_line,
        },
        "tables": {
            "summary": summary,
            "pv_table": pv_rows,
        },
    }


def save_troubleshooting_run(
    db: Session,
    result: dict,
    created_by: str = "system",
    notes: str | None = None,
) -> str:
    inv = result.get("problem_inverter") or {}
    win = result.get("window") or {}
    base = result.get("baseline") or {}
    k = result.get("kpis") or {}

    run_id = db.execute(
        text(
            """
            INSERT INTO troubleshooting_runs (
              device_sn, plant_name, model,
              window_start, window_end,
              classification, severity,
              median_power_ratio, median_temp_c,
              baseline_type, peer_count,
              created_by, notes
            )
            VALUES (
              :device_sn, :plant_name, :model,
              :window_start, :window_end,
              :classification, :severity,
              :median_power_ratio, :median_temp_c,
              :baseline_type, :peer_count,
              :created_by, :notes
            )
            RETURNING id
            """
        ),
        {
            "device_sn": inv.get("device_sn"),
            "plant_name": inv.get("plant_name"),
            "model": inv.get("model"),
            "window_start": win.get("start"),
            "window_end": win.get("end"),
            "classification": result.get("classification"),
            "severity": result.get("severity"),
            "median_power_ratio": k.get("median_power_ratio"),
            "median_temp_c": k.get("median_temp_c"),
            "baseline_type": base.get("type"),
            "peer_count": base.get("peer_count"),
            "created_by": created_by,
            "notes": notes,
        },
    ).scalar_one()

    db.execute(
        text(
            """
            INSERT INTO troubleshooting_run_data (run_id, payload)
            VALUES (:run_id, :payload::jsonb)
            """
        ),
        {
            "run_id": str(run_id),
            "payload": json.dumps(result),
        },
    )

    db.commit()
    return str(run_id)
