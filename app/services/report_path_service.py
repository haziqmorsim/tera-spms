from __future__ import annotations
from pathlib import Path

REPORTS_DIR = Path("reports")

EXCEL_DIR = REPORTS_DIR / "excel"
EXCEL_ALARMS_DIR = EXCEL_DIR / "alarms"
EXCEL_PLANTS_DIR = EXCEL_DIR / "plants"
EXCEL_INVERTERS_DIR = EXCEL_DIR / "inverters"
EXCEL_STRINGS_DIR = EXCEL_DIR / "strings"
EXCEL_OVERALL_DIR = EXCEL_DIR / "overall"

MONTHLY_REPORTS_DIR = REPORTS_DIR / "monthly"
TROUBLESHOOTING_REPORTS_DIR = REPORTS_DIR / "troubleshooting"

def ensure_report_directories() -> None:
    for folder in [
        EXCEL_ALARMS_DIR,
        EXCEL_PLANTS_DIR,
        EXCEL_INVERTERS_DIR,
        EXCEL_STRINGS_DIR,
        EXCEL_OVERALL_DIR,
        MONTHLY_REPORTS_DIR,
        TROUBLESHOOTING_REPORTS_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)