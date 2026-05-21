from __future__ import annotations
import os
from typing import List, Tuple
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.playwright_client import scrape_inverter_detail_telemetry
from app.services.telemetry_store import upsert_telemetry_5m

load_dotenv()

BASE = "https://intl.fusionsolar.huawei.com"
STATE_FILE = "fusionsolar_state.json"
ROW_SEL = "tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)"


def pick_targets(db, limit: int = 20) -> List[Tuple[str, str]]:
    rows = db.execute(
        text(
            """
            SELECT device_sn, plant_name
            FROM inverters
            WHERE device_sn IS NOT NULL AND device_sn <> '' AND device_sn <> '--'
            ORDER BY last_telemetry_ts NULLS FIRST, last_seen_ts NULLS FIRST
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).fetchall()

    return [(r[0], r[1]) for r in rows]


def goto_inverter_list(page) -> None:
    url = os.getenv("FUSIONSOLAR_INVERTER_LIST_URL")
    if url:
        page.goto(url, wait_until="domcontentloaded")
        return

    # Fallback (not ideal for scheduling)
    print("FUSIONSOLAR_INVERTER_LIST_URL not set.")
    print("Please navigate to the global inverter list page, then press ENTER.")
    input("ENTER when inverter list is visible...")


def set_page_size_100(page) -> None:
    try:
        page.locator(".ant-pagination-options-size-changer").click()
        page.wait_for_timeout(250)
        page.locator("text=100 / page").click()

        # Wait until applied (row count increases beyond the default 10)
        for _ in range(40):
            if page.locator(ROW_SEL).count() > 10:
                break
            page.wait_for_timeout(250)
    except Exception:
        # Not fatal
        pass


def filter_by_sn_and_open(page, device_sn: str) -> bool:
    sn_input = None
    candidates = [
        "input[placeholder='SN']",
        "input[aria-label='SN']",
        "xpath=//label[contains(.,'SN')]/following::input[1]",
        "xpath=//*[contains(text(),'SN')]/following::input[1]",
    ]
    for sel in candidates:
        loc = page.locator(sel)
        if loc.count() > 0:
            sn_input = loc.first
            break

    if sn_input is None:
        raise RuntimeError("Could not find SN input on inverter list page.")

    # Clear + fill SN
    sn_input.click()
    sn_input.fill("")
    sn_input.type(device_sn, delay=30)

    # Click Search within filter bar (avoid strict-mode ambiguity)
    filter_bar = page.locator("div:has(input[placeholder='SN'])")
    if filter_bar.count() == 0:
        filter_bar = page.locator("form")

    search_btn = filter_bar.get_by_role("button", name="Search")
    if search_btn.count() == 0:
        search_btn = filter_bar.locator("button.ant-btn-primary")

    search_btn.first.click()

    # Wait for rows
    page.wait_for_selector(ROW_SEL, timeout=60000)

    first_row = page.locator(ROW_SEL).first
    if first_row.count() == 0:
        return False

    # Device name is typically the 3rd td (after checkbox + status icon)
    cell_link = first_row.locator("td:nth-child(3) a")
    if cell_link.count() > 0:
        cell_link.first.click()
        return True

    first_row.locator("td:nth-child(3)").click()
    return True


def main() -> None:
    batch_size = int(os.getenv("TELEMETRY_BATCH_SIZE", "20"))

    ok = 0
    fail = 0
    run_id = None

    # Create run + pick targets in a single DB session
    db = SessionLocal()
    try:
        run_id = db.execute(
            text("INSERT INTO sync_runs(job_name) VALUES ('telemetry_5m') RETURNING id")
        ).scalar()
        db.commit()

        targets = pick_targets(db, limit=batch_size)

        if not targets:
            # Close the run cleanly
            db.execute(
                text(
                    """
                    UPDATE sync_runs
                    SET finished_at = now(), ok_count = 0, fail_count = 0, notes = 'No targets'
                    WHERE id = :id
                    """
                ),
                {"id": run_id},
            )
            db.commit()
            print("No targets found.")
            return
    finally:
        db.close()

    # Playwright scraping + upsert
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = (
            browser.new_context(storage_state=STATE_FILE)
            if os.path.exists(STATE_FILE)
            else browser.new_context()
        )
        page = context.new_page()
        page.goto(BASE, wait_until="domcontentloaded")

        # Login once if needed; then persist state
        if "login/build/index.html" in page.url:
            print("Please log in in the browser window...")
            page.wait_for_function(
                "(() => !window.location.href.includes('/pvmswebsite/login/build/index.html'))()",
                timeout=180000,
            )

        context.storage_state(path=STATE_FILE)

        # Go to inverter list page and set page size
        goto_inverter_list(page)
        page.wait_for_selector(ROW_SEL, timeout=60000)
        set_page_size_100(page)

        db2 = SessionLocal()
        try:
            for device_sn, plant_name in targets:
                try:
                    goto_inverter_list(page)
                    page.wait_for_selector(ROW_SEL, timeout=60000)

                    opened = filter_by_sn_and_open(page, device_sn)
                    if not opened:
                        print("No row found for SN:", device_sn)
                        fail += 1
                        continue

                    page.wait_for_selector(
                        "div.nco-realtime-info-signal-wrapper", timeout=60000
                    )

                    telemetry = scrape_inverter_detail_telemetry(page)

                    ts_used = upsert_telemetry_5m(
                        db2,
                        device_sn=device_sn,
                        plant_name=plant_name,
                        telemetry=telemetry,
                    )

                    ok += 1
                    print(
                        f"[OK] {device_sn} @ {ts_used.isoformat()} power={telemetry.get('active_power_kw')}"
                    )

                    page.go_back()
                    page.wait_for_timeout(400)

                except Exception as e:
                    fail += 1
                    print(f"[FAIL] {device_sn} error={e}")
                    try:
                        goto_inverter_list(page)
                    except Exception:
                        pass

        finally:
            # Always close the sync_runs record
            db3 = SessionLocal()
            try:
                db3.execute(
                    text(
                        """
                        UPDATE sync_runs
                        SET finished_at = now(),
                            ok_count = :ok,
                            fail_count = :fail
                        WHERE id = :id
                        """
                    ),
                    {"ok": ok, "fail": fail, "id": run_id},
                )
                db3.commit()
            finally:
                db3.close()

            db2.close()
            browser.close()

    print(
        f"Telemetry batch is complete. Ok = {ok} Fail = {fail} Total = {len(targets)}"
    )


if __name__ == "__main__":
    main()
