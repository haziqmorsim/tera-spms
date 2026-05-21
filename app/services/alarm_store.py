from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_alarm(db: Session, alarm: dict) -> None:
    db.execute(
        text(
            """
            INSERT INTO alarms (
                device_sn,
                device_name,
                plant_name,
                device_type,
                alarm_id,
                alarm_name,
                severity,
                occurrence_ts,
                is_active,
                cleared_ts
            )
            VALUES (
                :device_sn,
                :device_name,
                :plant_name,
                :device_type,
                :alarm_id,
                :alarm_name,
                :severity,
                :occurrence_ts,
                true,
                NULL
            )
            ON CONFLICT (device_sn, alarm_id, occurrence_ts)
            DO UPDATE SET
                device_name = EXCLUDED.device_name,
                plant_name = EXCLUDED.plant_name,
                device_type = EXCLUDED.device_type,
                alarm_name = EXCLUDED.alarm_name,
                severity = EXCLUDED.severity,
                is_active = true,
                cleared_ts = NULL,
                updated_at = now();
            """
        ),
        alarm,
    )


def mark_missing_alarm_inactive(
    db: Session, active_keys: list[tuple[str, str, datetime]]
) -> None:
    if not active_keys:
        db.execute(
            text(
                """
                UPDATE alarms
                SET
                    is_active = false,
                    cleared_ts = COALESCE(cleared_ts, now()),
                    updated_at = now()
                WHERE is_active = true;
                """
            )
        )
        return

    values_sql_parts = []
    params = {}

    for i, (device_sn, alarm_id, occurrence_ts) in enumerate(active_keys):
        values_sql_parts.append(
            f"(:device_sn_{i}, :alarm_id_{i}, CAST(:occurrence_ts_{i} AS TIMESTAMPTZ))"
        )
        params[f"device_sn_{i}"] = device_sn
        params[f"alarm_id_{i}"] = alarm_id
        params[f"occurrence_ts_{i}"] = occurrence_ts

    values_sql = ", ".join(values_sql_parts)

    sql = f"""
        WITH active_now(device_sn, alarm_id, occurrence_ts) AS (
            VALUES {values_sql}
        )
        UPDATE alarms a
        SET
            is_active = false,
            cleared_ts = COALESCE(cleared_ts, now()),
            updated_at = now()
        WHERE a.is_active = true
          AND NOT EXISTS (
              SELECT 1
              FROM active_now x
              WHERE x.device_sn = a.device_sn
                AND x.alarm_id = a.alarm_id
                AND x.occurrence_ts = a.occurrence_ts
          );
    """

    db.execute(text(sql), params)