from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.alarm_scraper import extract_alarm_rows
from app.services.alarm_store import mark_missing_alarm_inactive, upsert_alarm
from app.services.alarm_xlsx_report_service import build_alarm_xlsx_report
from app.services.playwright_client import (
    create_fusionsolar_context,
    dismiss_cookie_policy,
    open_fusionsolar_target,
)
from app.services.report_storage_service import save_generated_report
from app.services.report_path_service import EXCEL_ALARMS_DIR, ensure_report_directories
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "poll_alarms"
ROW_SEL = "tbody.dpdesign-table-tbody > tr.dpdesign-table-row:not(.dpdesign-table-measure-row)"
PLANT_INFO_EXCEL = Path("Service Performance Monitoring System Plant Information.xlsx")

def set_page_size_100(page):
    try:
        dismiss_cookie_policy(page)

        changer = page.locator(".ant-pagination-options-size-changer")
        if changer.count() == 0:
            print("No page size changer found on alarms page.")
            return False

        changer.first.click()
        page.wait_for_timeout(600)

        opt = page.locator(".ant-select-item-option[title='100 / page']")
        if opt.count() == 0:
            opt = page.locator("text='100 / page'")

        if opt.count() > 0:
            opt.first.click()
            page.wait_for_timeout(1200)
            dismiss_cookie_policy(page)
            print("Alarm page size is set to 100.")
            return True

        print("Could not find 100 / page option.")
        return False
    except Exception as e:
        print("Could not set alarm page size:", e)
        return False

def wait_for_alarm_table_or_empty(page):
    dismiss_cookie_policy(page)

    try:
        page.wait_for_selector(ROW_SEL, timeout=15000)
        dismiss_cookie_policy(page)
        return "rows"
    except Exception:
        pass

    empty_selectors = [
        ".ant-empty",
        ".ant-table-placeholder",
        "text=No Data",
        "text=No data",
        "text=No alarm",
        "text=No Alarm",
    ]

    for sel in empty_selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.wait_for(state="visible", timeout=3000)
                dismiss_cookie_policy(page)
                return "empty"
        except Exception:
            continue

    return "unknown"

def go_to_next_alarm_page(page) -> bool:
    dismiss_cookie_policy(page)

    next_li = page.locator("li.ant-pagination-next")
    if next_li.count() == 0:
        return False

    next_li = next_li.first
    next_class = next_li.get_attribute("class") or ""
    aria_disabled = next_li.get_attribute("aria-disabled") or "false"

    if "ant-pagination-disabled" in next_class or aria_disabled == "true":
        return False

    active_before = ""
    try:
        active_before = page.locator("li.ant-pagination-item-active").inner_text().strip()
    except Exception:
        active_before = ""

    next_btn = next_li.locator("button").first
    if next_btn.count() == 0:
        return False

    try:
        next_btn.click(timeout=5000, no_wait_after=True)
    except Exception:
        dismiss_cookie_policy(page)
        try:
            next_btn.click(timeout=3000, no_wait_after=True, force=True)
        except Exception:
            next_li.click(timeout=3000, no_wait_after=True, force=True)

    if active_before:
        try:
            page.wait_for_function(
                """(before) => {
                    const el = document.querySelector('li.ant-pagination-item-active');
                    return el && el.innerText.trim() !== before;
                }""",
                arg=active_before,
                timeout=15000,
            )
        except Exception:
            page.wait_for_timeout(1200)
    else:
        page.wait_for_timeout(1200)

    dismiss_cookie_policy(page)
    page.wait_for_timeout(600)
    return True


def main():
    alarm_url = os.getenv("FUSIONSOLAR_ALARM_LIST_URL", "").strip()
    if not alarm_url:
        raise RuntimeError("FUSIONSOLAR_ALARM_LIST_URL is not set in .env")

    db = SessionLocal()
    run_id = None

    try:
        ensure_report_directories()

        run_id = start_run(db, JOB_NAME)

        all_rows = []

        with sync_playwright() as p:
            browser, context = create_fusionsolar_context(p, headless=False)
            page = context.new_page()

            open_fusionsolar_target(
                page,
                context,
                alarm_url,
                interactive_login=False,
            )
            dismiss_cookie_policy(page)

            state = wait_for_alarm_table_or_empty(page)

            if state == "unknown":
                browser.close()
                raise RuntimeError(
                    "Alarm table was not detected automatically. Check that "
                    "FUSIONSOLAR_ALARM_LIST_URL is correct and the saved session is valid."
                )

            if state == "empty":
                print("Alarm page is empty. No alarms found.")
            elif state == "rows":
                set_page_size_100(page)

                page_no = 1
                first_alarm_row = None

                while True:
                    dismiss_cookie_policy(page)
                    state = wait_for_alarm_table_or_empty(page)

                    if state == "empty":
                        print("Alarm page is empty. No alarms found.")
                        break

                    if state != "rows":
                        print("Could not detect alarm rows. Stopping.")
                        break

                    rows, first_row = extract_alarm_rows(page, ROW_SEL)

                    if first_alarm_row is None:
                        first_alarm_row = first_row

                    print(f"Alarm page {page_no} rows: {len(rows)}")
                    all_rows.extend(rows)

                    moved = go_to_next_alarm_page(page)
                    if not moved:
                        break

                    page_no += 1

                if first_alarm_row:
                    print("First alarm row enumerate:", list(enumerate(first_alarm_row)))
            else:
                browser.close()
                raise RuntimeError("Could not detect alarm rows automatically.")

            browser.close()

        active_keys = []

        for row in all_rows:
            upsert_alarm(db, row)
            active_keys.append(
                (
                    row["device_sn"],
                    row["alarm_id"],
                    row["occurrence_ts"],
                )
            )

        mark_missing_alarm_inactive(db, active_keys)
        db.commit()

        report_day = today_gmt8()
        report_path = report_path = (EXCEL_ALARMS_DIR / f"alarms_report_{report_day.strftime('%d-%m-%Y')}.xlsx")

        if not PLANT_INFO_EXCEL.exists():
            raise FileNotFoundError(
                f"Plant info workbook not found: {PLANT_INFO_EXCEL}"
            )

        build_alarm_xlsx_report(
            alarm_rows=all_rows,
            plant_info_excel_path=PLANT_INFO_EXCEL,
            output_path=report_path,
        )

        save_generated_report(
            report_type="ALARMS_XLSX",
            file_path=str(report_path),
            local_file_path=str(report_path),
            report_day=report_day,
        )

        active_count = db.execute(
            text(
                """
                SELECT COUNT(*)::int
                FROM alarms
                WHERE is_active = true
                """
            )
        ).scalar_one()

        message = (
            f"Active alarms: {active_count}\n"
            f"File: {report_path.name}"
        )

        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "total_alarms": len(all_rows),
                "active_alarms": active_count,
                "report_file": report_path.name,
            },
        )

        print(f"Alarm polling is complete. {message}")

    except Exception as e:
        db.rollback()
        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))
        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()