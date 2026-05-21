from sqlalchemy import text


def fetch_troubleshooting_report_rows(db, day):
    rows = (
        db.execute(
            text(
                """
        SELECT x.day, x.plant_name, x.device_sn, i.device_name, x.inverter_psh, x.plant_avg_psh, x.inverter_vs_plant_psh_pct, x.likely_issue, x.missing_pvs, x.weak_pvs, x.internal_temperature_c, x.alarm_name, x.alarm_severity, a.anomaly_score, a.is_anomaly 
        FROM v_low_psh_problem_inverters x 
        LEFT JOIN inverters i 
            ON x.device_sn = i.device_sn 
        LEFT JOIN ai_detection_results a 
            ON a.day = x.day 
            AND a.device_sn = x.device_sn 
            AND a.plant_name = x.plant_name 
        WHERE x.day = :day
        ORDER BY x.plant_name, i.device_name, x.device_sn
    """
            ),
            {"day": day},
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in rows]


def build_report_summary(rows: list[dict]) -> dict:
    plants = set()
    devices = set()
    ai_anomalies = 0
    alarms = 0
    high_temp = 0
    pv_issues = 0

    for r in rows:
        plants.add(r["plant_name"])
        devices.add(r["device_sn"])

        if r.get("is_anomaly") is True:
            ai_anomalies += 1

        if r.get("alarm_name"):
            alarms += 1

        temp = r.get("internal_temperature_c")
        if temp is not None and temp >= 70:
            high_temp += 1

        missing_pvs = r.get("missing_pvs")
        weak_pvs = r.get("weak_pvs")
        if missing_pvs or weak_pvs:
            pv_issues += 1

    return {
        "total_plants": len(plants),
        "total_problem_inverters": len(devices),
        "total_ai_anomalies": ai_anomalies,
        "total_alarm_cases": alarms,
        "total_high_temperature": high_temp,
        "total_pv_issues": pv_issues,
    }


def build_plant_summaries(rows: list[dict]) -> list[dict]:
    grouped = {}

    for r in rows:
        plant = r["plant_name"]

        if plant not in grouped:
            grouped[plant] = {
                "plant_name": plant,
                "problem_inverters": 0,
                "avg_plant_psh_values": [],
                "ai_anomalies": 0,
                "alarms": 0,
                "high_temperature": 0,
            }

        grouped[plant]["problem_inverters"] += 1

        if r.get("plant_avg_psh") is not None:
            grouped[plant]["avg_plant_psh_values"].append(r["plant_avg_psh"])

        if r.get("is_anomaly") is True:
            grouped[plant]["ai_anomalies"] += 1

        if r.get("alarm_name"):
            grouped[plant]["alarms"] += 1

        temp = r.get("internal_temperature_c")
        if temp is not None and temp >= 70:
            grouped[plant]["high_temperature"] += 1

    result = []
    for plant, data in grouped.items():
        psh_values = data.pop("avg_plant_psh_values")
        data["plant_avg_psh_overall"] = (
            round(sum(psh_values) / len(psh_values), 3) if psh_values else None
        )
        result.append(data)

    return sorted(result, key=lambda x: x["plant_name"])


def group_inverter_details_by_plant(rows: list[dict]) -> dict:
    grouped = {}

    for r in rows:
        plant = r["plant_name"]
        grouped.setdefault(plant, []).append(r)

    return grouped


def build_issue_breakdown(rows: list[dict]) -> dict:
    counts = {}

    for r in rows:
        issue = r.get("likely_issue") or "UNKNOWN"
        counts[issue] = counts.get(issue, 0) + 1

    return dict(sorted(counts.items(), key=lambda x: x[0]))


def build_troubleshooting_report_payload(db, day):
    rows = fetch_troubleshooting_report_rows(db, day)

    return {
        "day": day,
        "summary": build_report_summary(rows),
        "plant_summaries": build_plant_summaries(rows),
        "issue_breakdown": build_issue_breakdown(rows),
        "plant_details": group_inverter_details_by_plant(rows),
        "rows": rows,
    }
