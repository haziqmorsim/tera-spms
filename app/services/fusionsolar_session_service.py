from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from app.utils.time_utils import APP_TZ, format_datetime_gmt8

load_dotenv()

def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def get_fusionsolar_state_file() -> Path:
    raw = os.getenv("FUSIONSOLAR_STATE_FILE", "fusionsolar_state.json").strip()
    if not raw:
        raw = "fusionsolar_state.json"

    path = Path(raw)

    if not path.is_absolute():
        path = get_project_root() / path

    return path.resolve()

STATE_FILE = get_fusionsolar_state_file()

def _login_required(url: str) -> bool:
    url = (url or "").lower()
    return (
        "login/build/index.html" in url 
        or "/login/" in url 
        or "/user/login" in url
    )

def _get_check_url() -> str:
    candidates = [
        os.getenv("FUSIONSOLAR_HOME_URL", "").strip(),
        os.getenv("FUSIONSOLAR_INVERTER_LIST_URL", "").strip(),
        os.getenv("FUSIONSOLAR_ALARM_LIST_URL", "").strip(),
        os.getenv("FUSIONSOLAR_LOGIN_URL", "").strip(),
        os.getenv("FUSIONSOLAR_BASE_URL", "https://intl.fusionsolar.huawei.com").strip(),
    ]

    for url in candidates:
        if url:
            return url
        
    return "https://intl.fusionsolar.huawei.com/"

def _check_fusionsolar_session_valid() -> tuple[bool, str]:
    if not STATE_FILE.exists() or not STATE_FILE.is_file():
        return False, "FusionSolar session file is missing."
    
    check_url = _get_check_url()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(STATE_FILE))
            page = context.new_page()

            page.goto(check_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            current_url = page.url or ""

            browser.close()
        
        if _login_required(current_url):
            return False, (
                "FusionSolar session exists but the saved session has expired."
            )
        
        return True, "FusionSolar session file is valid and available."
    
    except Exception as e:
        return False, (
            "FusionSolar session exists but could not be validated. "
            f"Error: {e}"
        )

def get_fusionsolar_session_status() -> dict:
    exists = STATE_FILE.exists() and STATE_FILE.is_file()

    if not exists:
        return {
            "exists": False,
            "file_path": STATE_FILE.as_posix(),
            "file_name": STATE_FILE.name,
            "last_modified": None,
            "size_bytes": 0,
            "size_kb": 0,
            "status": "missing",
            "message": (
                "FusionSolar session file is missing. "
                "Run 'python -m scripts.save_fusionsolar_session' to create a new session."
            ),
        }

    stat = STATE_FILE.stat()
    modified_dt = datetime.fromtimestamp(stat.st_mtime, APP_TZ)

    is_valid, validation_message = _check_fusionsolar_session_valid()

    return {
        "exists": True,
        "file_path": STATE_FILE.as_posix(),
        "file_name": STATE_FILE.name,
        "last_modified": format_datetime_gmt8(modified_dt),
        "size_bytes": int(stat.st_size),
        "size_kb": round(stat.st_size / 1024, 2),
        "status": "available" if is_valid else "expired",
        "message": validation_message,
    }

def delete_fusionsolar_session_file() -> dict:
    if STATE_FILE.exists() and STATE_FILE.is_file():
        STATE_FILE.unlink()

    return {
        "message": "FusionSolar session file deleted successfully."
    }