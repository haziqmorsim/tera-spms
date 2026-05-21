from __future__ import annotations
from datetime import datetime
from typing import Dict, List


def parse_occurrence_time(text: str) -> datetime:
    text = text.strip()
    return datetime.fromisoformat(text) # 2026-03-10 07:12:00 +08:00


def extract_alarm_rows(page, row_selector: str):
    rows = page.query_selector_all(row_selector)
    result: List[Dict] = []
    first_row_values = None

    for idx, row in enumerate(rows):
        tds = row.query_selector_all("td")
        values = [td.inner_text().strip() for td in tds]

        if first_row_values is None and idx == 0:
            first_row_values = values

        if len(values) < 9:
            continue

        result.append(
            {
                "severity": values[1],
                "plant_name": values[2],
                "device_type": values[3],
                "device_name": values[4],
                "device_sn": values[5],
                "alarm_id": values[6],
                "alarm_name": values[7],
                "occurrence_ts": parse_occurrence_time(values[8]),
            }
        )

    return result, first_row_values
