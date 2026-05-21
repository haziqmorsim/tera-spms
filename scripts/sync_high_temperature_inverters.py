from __future__ import annotations
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.playwright_client import (
    create_fusionsolar_context,
    dismiss_cookie_policy,
    go_to_next_table_page,
    open_fusionsolar_target,
    open_inverter_detail_in_new_tab_by_row_index,
    scrape_inverter_detail_telemetry,
    set_page_size_300,
    wait_for_inverter_list_ready,
)
from app.utils.job_logger import finish_run, start_run
from app.utils.time_utils import today_gmt8

load_dotenv()

JOB_NAME = "sync_high_temperature_inverters"
TEMP_THRESHOLD_C = float(os.getenv("TEMP_THRESHOLD_C", "70"))

def ensure_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS high_temperature_inverters_latest (
                run_day date NOT NULL,
                plant_name text NOT NULL,
                device_name text NOT NULL,
                device_sn text NOT NULL,
                internal_temperature_c double precision,
                source_ts timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (run_day, device_sn)
            )
            """
        )
    )
    db.commit()

def replace_run_snapshot(db, run_day, rows: list[dict]) -> None:
    db.execute(
        text(
            """
            DELETE FROM high_temperature_inverters_latest
            WHERE run_day = :run_day
            """
        ),
        {"run_day": run_day},
    )

    for row in rows:
        db.execute(
            text(
                """
                INSERT INTO high_temperature_inverters_latest (
                    run_day,
                    plant_name,
                    device_name,
                    device_sn,
                    internal_temperature_c
                )
                VALUES (
                    :run_day,
                    :plant_name,
                    :device_name,
                    :device_sn,
                    :internal_temperature_c
                )
                """
            ),
            {
                "run_day": run_day,
                "plant_name": row["plant_name"],
                "device_name": row["device_name"],
                "device_sn": row["device_sn"],
                "internal_temperature_c": row["internal_temperature_c"],
            },
        )

    db.commit()

def prepare_inverter_list_page(page) -> None:
    wait_for_inverter_list_ready(page)
    dismiss_cookie_policy(page)
    set_page_size_300(page, page_label="inverter list")
    wait_for_inverter_list_ready(page)
    dismiss_cookie_policy(page)

def main():
    inverter_url = os.getenv("FUSIONSOLAR_INVERTER_LIST_URL", "").strip()
    if not inverter_url:
        raise RuntimeError("FUSIONSOLAR_INVERTER_LIST_URL is not set in .env")

    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)
        ensure_table(db)

        run_day = today_gmt8()
        matched_rows: list[dict] = []

        checked_count = 0
        row_number = 0

        with sync_playwright() as p:
            _, context = create_fusionsolar_context(p, headless=False)
            list_page = context.new_page()

            try:
                open_fusionsolar_target(
                    list_page,
                    context,
                    inverter_url,
                    interactive_login=False,
                )
                prepare_inverter_list_page(list_page)

                while True:
                    dismiss_cookie_policy(list_page)

                    rows = list_page.locator(
                        "tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)"
                    )
                    if rows.count() == 0:
                        rows = list_page.locator(
                            "tbody.dpdesign-table-tbody > tr.dpdesign-table-row:not(.dpdesign-table-measure-row)"
                        )
                    if rows.count() == 0:
                        rows = list_page.locator("tbody tr")

                    current_page_row_count = rows.count()
                    if current_page_row_count == 0:
                        break

                    for row_index in range(current_page_row_count):
                        row_number += 1
                        detail_page = None

                        try:
                            dismiss_cookie_policy(list_page)

                            detail_page, summary = open_inverter_detail_in_new_tab_by_row_index(
                                list_page,
                                context,
                                row_index,
                            )
                            checked_count += 1

                            plant_name = summary.get("plant_name", "")
                            device_name = summary.get("device_name", "")
                            device_sn = summary.get("device_sn", "")

                            dismiss_cookie_policy(detail_page)
                            telemetry = scrape_inverter_detail_telemetry(detail_page)
                            temp = telemetry.get("internal_temperature_c")

                            if temp is not None and float(temp) >= TEMP_THRESHOLD_C:
                                matched_rows.append(
                                    {
                                        "plant_name": plant_name,
                                        "device_name": device_name,
                                        "device_sn": device_sn,
                                        "internal_temperature_c": float(temp),
                                    }
                                )
                                print(
                                    f"{row_number}. [OK] {plant_name} | {device_name} | "
                                    f"SN = {device_sn} | Temperature = {float(temp):.1f}"
                                )
                            else:
                                print(
                                    f"{row_number}. [OK] {plant_name} | {device_name} | "
                                    f"SN = {device_sn} | Temperature = "
                                    f"{temp if temp is not None else '-'}"
                                )

                        except Exception as e:
                            print(f"{row_number}. [FAIL] row {row_index + 1} -> {e}")

                        finally:
                            try:
                                if detail_page is not None and not detail_page.is_closed():
                                    detail_page.close()
                            except Exception:
                                pass

                            try:
                                list_page.bring_to_front()
                                dismiss_cookie_policy(list_page)
                            except Exception:
                                pass

                    moved = go_to_next_table_page(list_page)
                    if not moved:
                        break

                    wait_for_inverter_list_ready(list_page)
                    dismiss_cookie_policy(list_page)

            finally:
                context.close()

        replace_run_snapshot(db, run_day, matched_rows)

        message = (
            f"Inverters checked: {checked_count}\n"
            f"High-temperature inverters: {len(matched_rows)}\n"
            f"Threshold: {TEMP_THRESHOLD_C}°C"
        )
        finish_run(
            db,
            run_id,
            "success",
            message,
            {
                "checked_count": checked_count,
                "matched_count": len(matched_rows),
                "threshold_c": TEMP_THRESHOLD_C,
            },
        )
        print(message)

    except Exception as e:
        db.rollback()
        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))
        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()