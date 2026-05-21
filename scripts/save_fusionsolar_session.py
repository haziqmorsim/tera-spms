from __future__ import annotations
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from app.services.fusionsolar_session_service import STATE_FILE
from app.services.playwright_client import (
    auto_login_fusionsolar,
    dismiss_cookie_policy,
    wait_for_login_success,
)

load_dotenv()

def main() -> None:
    login_url = (
        os.getenv("FUSIONSOLAR_LOGIN_URL", "").strip()
        or "https://intl.fusionsolar.huawei.com/"
    )

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        page.goto(login_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        dismiss_cookie_policy(page)

        print("Opening FusionSolar login page...")
        auto_result = auto_login_fusionsolar(page)

        if auto_result:
            print("Automatic FusionSolar login was submitted. Waiting for completion...")
        else:
            print("Automatic login could not be completed.")
            print("Please log in manually in the browser window.")
            print("The session will be saved automatically after login succeeds.")

        wait_for_login_success(page, timeout_seconds=300)

        context.storage_state(path=str(STATE_FILE))
        browser.close()

    print(f"FusionSolar session saved successfully to: {STATE_FILE.as_posix()}")

if __name__ == "__main__":
    main()