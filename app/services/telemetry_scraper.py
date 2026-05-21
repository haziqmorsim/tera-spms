from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "--":
        return None
    return text


def _to_float(value: str | None) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None

    cleaned = text.replace(",", "").strip()
    cleaned = re.sub(r"[^\d.\-]", "", cleaned)

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_key(key: str) -> str:
    key = key.strip().lower()

    mapping = {
        "status": "inverter_status",
        "active power": "active_power_kw",
        "daily energy": "daily_energy_kwh",
        "yield today": "daily_energy_kwh",
        "total yield": "total_yield_kwh",
        "grid frequency": "grid_frequency_hz",
        "internal temperature": "internal_temperature_c",
        "power factor": "power_factor",
        "reactive power": "reactive_power_kvar",
        "phase a current": "grid_phase_a_current_a",
        "phase b current": "grid_phase_b_current_a",
        "phase c current": "grid_phase_c_current_a",
        "phase a voltage": "phase_a_voltage_v",
        "phase b voltage": "phase_b_voltage_v",
        "phase c voltage": "phase_c_voltage_v",
        "insulation resistance": "insulation_resistance_mohm",
        "input voltage|pv1": "pv1_voltage_v",
        "input current|pv1": "pv1_current_a",
        "input voltage|pv2": "pv2_voltage_v",
        "input current|pv2": "pv2_current_a",
        "input voltage|pv3": "pv3_voltage_v",
        "input current|pv3": "pv3_current_a",
        "input voltage|pv4": "pv4_voltage_v",
        "input current|pv4": "pv4_current_a",
    }

    # direct exact match first
    if key in mapping:
        return mapping[key]

    # looser contains-based matching
    if "internal temperature" in key:
        return "internal_temperature_c"
    if "active power" in key:
        return "active_power_kw"
    if "daily energy" in key or "yield today" in key:
        return "daily_energy_kwh"
    if "total yield" in key:
        return "total_yield_kwh"
    if "grid frequency" in key:
        return "grid_frequency_hz"
    if "power factor" in key:
        return "power_factor"
    if "reactive power" in key:
        return "reactive_power_kvar"
    if "insulation resistance" in key:
        return "insulation_resistance_mohm"

    if "phase a current" in key:
        return "grid_phase_a_current_a"
    if "phase b current" in key:
        return "grid_phase_b_current_a"
    if "phase c current" in key:
        return "grid_phase_c_current_a"

    if "phase a voltage" in key:
        return "phase_a_voltage_v"
    if "phase b voltage" in key:
        return "phase_b_voltage_v"
    if "phase c voltage" in key:
        return "phase_c_voltage_v"

    if "input voltage|pv1" in key:
        return "pv1_voltage_v"
    if "input current|pv1" in key:
        return "pv1_current_a"
    if "input voltage|pv2" in key:
        return "pv2_voltage_v"
    if "input current|pv2" in key:
        return "pv2_current_a"
    if "input voltage|pv3" in key:
        return "pv3_voltage_v"
    if "input current|pv3" in key:
        return "pv3_current_a"
    if "input voltage|pv4" in key:
        return "pv4_voltage_v"
    if "input current|pv4" in key:
        return "pv4_current_a"

    return key.replace(" ", "_").replace("/", "_").replace("-", "_")


def parse_realtime_kv(pairs: dict[str, str]) -> dict:
    telemetry: dict[str, object] = {}

    for raw_key, raw_value in pairs.items():
        key = _normalize_key(raw_key)
        value_text = _clean_text(raw_value)

        if value_text is None:
            telemetry[key] = None
            continue

        if key == "inverter_status":
            telemetry[key] = value_text
        else:
            telemetry[key] = _to_float(value_text)

    return telemetry