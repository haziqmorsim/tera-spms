from __future__ import annotations
import os
import re
import time
from urllib.parse import urljoin
from dotenv import load_dotenv
from playwright.sync_api import Browser, BrowserContext, Page
from app.services.fusionsolar_session_service import STATE_FILE
from app.services.telemetry_scraper import parse_realtime_kv

load_dotenv()

BASE = os.getenv("FUSIONSOLAR_BASE_URL", "https://intl.fusionsolar.huawei.com").rstrip("/")
HOME_URL = os.getenv("FUSIONSOLAR_HOME_URL", "").strip()
INVERTER_LIST_URL = os.getenv("FUSIONSOLAR_INVERTER_LIST_URL", "").strip()

ROW_SEL = "tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)"
DETAIL_KV_ROW = "div:has-text('Real-Time Device Data')"

def _login_required(url: str) -> bool:
    url = (url or "").lower()
    return (
        "login/build/index.html" in url
        or "/login/" in url
        or "/user/login" in url
    )

def get_fusionsolar_username() -> str:
    return os.getenv("FUSIONSOLAR_USERNAME", "").strip()

def get_fusionsolar_password() -> str:
    return os.getenv("FUSIONSOLAR_PASSWORD", "").strip()

def has_fusionsolar_credentials() -> bool:
    return bool(get_fusionsolar_username() and get_fusionsolar_password())

def create_fusionsolar_context(
    playwright_obj,
    headless: bool = False,
) -> tuple[Browser, BrowserContext]:
    browser = playwright_obj.chromium.launch(
        headless=headless,
        args=["--start-maximized"] if not headless else [],
    )
    context = (
        browser.new_context(storage_state=str(STATE_FILE), no_viewport=True)
        if STATE_FILE.exists()
        else browser.new_context(no_viewport=True)
    )
    return browser, context

def dismiss_cookie_policy(page: Page) -> None:
    try:
        banner = page.locator("#cookie-policy")
        if banner.count() == 0:
            return
        if not banner.first.is_visible():
            return
    except Exception:
        return

    button_selectors = [
        "#cookie-policy button",
        "#cookie-policy .ant-btn",
        "#cookie-policy [role='button']",
        "#cookie-policy .close",
        "#cookie-policy .btn",
        "text=Accept",
        "text=I Agree",
        "text=Agree",
        "text=OK",
        "text=Got it",
    ]

    for sel in button_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=2000, no_wait_after=True)
                page.wait_for_timeout(300)
                try:
                    if page.locator("#cookie-policy").count() == 0:
                        return
                    if not page.locator("#cookie-policy").first.is_visible():
                        return
                except Exception:
                    return
        except Exception:
            continue

    try:
        page.evaluate(
            """
            () => {
                const el = document.querySelector('#cookie-policy');
                if (!el) return;
                el.style.display = 'none';
                el.style.visibility = 'hidden';
                if (typeof el.remove === 'function') el.remove();
            }
            """
        )
        page.wait_for_timeout(200)
    except Exception:
        pass

def wait_for_login_success(page: Page, timeout_seconds: int = 300) -> None:
    deadline = time.time() + timeout_seconds

    success_selectors = [
        ".ant-layout",
        ".ant-menu",
        ".ant-table-wrapper",
        "text=Plant",
        "text=Dashboard",
        "text=Device",
        "text=Alarm",
    ]

    while time.time() < deadline:
        dismiss_cookie_policy(page)

        current_url = page.url
        if current_url and not _login_required(current_url):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass

            page.wait_for_timeout(1500)
            dismiss_cookie_policy(page)

            for selector in success_selectors:
                try:
                    loc = page.locator(selector)
                    if loc.count() > 0 and loc.first.is_visible():
                        return
                except Exception:
                    continue

            return

        page.wait_for_timeout(1000)

    raise RuntimeError(
        "FusionSolar login was not completed within the timeout. "
        "Please try again and complete the login in the opened browser."
    )

def auto_login_fusionsolar(page: Page) -> bool:
    username = get_fusionsolar_username()
    password = get_fusionsolar_password()

    if not username or not password:
        return False

    dismiss_cookie_policy(page)

    username_selectors = [
        "#username input",
        "input[placeholder='Username or email']",
        "input[type='text'][placeholder*='Username']",
        "input[type='text']",
    ]

    password_selectors = [
        "#password input",
        "input[placeholder='Password']",
        "input[type='password']",
    ]

    login_button_selectors = [
        "#btn_outerverify",
        "#submitDataverify",
        "#login-button .loginBtn",
        ".loginBtn",
        "div.loginBtn",
        "text=Log In",
    ]

    user_input = None
    pass_input = None
    login_btn = None

    for sel in username_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                user_input = loc.first
                break
        except Exception:
            continue

    for sel in password_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                pass_input = loc.first
                break
        except Exception:
            continue

    for sel in login_button_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                login_btn = loc.first
                break
        except Exception:
            continue

    if not user_input or not pass_input or not login_btn:
        return False

    try:
        user_input.click(timeout=3000)
        user_input.fill("")
        user_input.type(username, delay=30)

        pass_input.click(timeout=3000)
        pass_input.fill("")
        pass_input.type(password, delay=30)

        dismiss_cookie_policy(page)
        page.wait_for_timeout(300)

        try:
            login_btn.click(timeout=5000, no_wait_after=True)
        except Exception:
            login_btn.click(timeout=3000, no_wait_after=True, force=True)

        page.wait_for_timeout(1500)
        dismiss_cookie_policy(page)
        return True
    except Exception:
        return False


def _wait_until_logged_in(page: Page, timeout_ms: int = 18000) -> None:
    page.wait_for_function(
        "(() => !window.location.href.includes('/pvmswebsite/login/build/index.html'))()",
        timeout=timeout_ms,
    )

def open_fusionsolar_target(
    page: Page,
    context: BrowserContext,
    target_url: str,
    *,
    interactive_login: bool = False,
) -> None:
    page.goto(target_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    dismiss_cookie_policy(page)

    if _login_required(page.url):
        auto_login_done = auto_login_fusionsolar(page)

        if auto_login_done:
            wait_for_login_success(page, timeout_seconds=120)
            context.storage_state(path=str(STATE_FILE))
            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            dismiss_cookie_policy(page)

        elif interactive_login:
            print("FusionSolar login is required.")
            print("Please login in the browser window. The session will be saved automatically.")
            wait_for_login_success(page, timeout_seconds=300)
            context.storage_state(path=str(STATE_FILE))

            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            dismiss_cookie_policy(page)
        else:
            raise RuntimeError(
                "FusionSolar session is not valid and automatic login could not be completed. "
                "Run 'python -m scripts.save_fusionsolar_session' to refresh the session."
            )

        if _login_required(page.url):
            raise RuntimeError("FusionSolar login did not complete successfully.")

    context.storage_state(path=str(STATE_FILE))

def wait_for_inverter_list_ready(page: Page, timeout: int = 20000) -> None:
    selectors = [
        ".ant-table-body",
        ROW_SEL,
        "tbody tr",
        ".ant-table-wrapper",
        "li.ant-pagination-total-text",
    ]

    last_error = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout)
            page.wait_for_timeout(500)
            dismiss_cookie_policy(page)
            return
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Could not detect inverter list table: {last_error}")

def _set_page_size(page: Page, page_size: int, row_sel: str, page_label: str) -> None:
    try:
        dismiss_cookie_policy(page)

        current_label = page.locator(".ant-pagination-options .ant-select-selection-item")
        if current_label.count() > 0:
            current_text = (current_label.first.inner_text() or "").strip().lower()
            if f"{page_size} / page".lower() in current_text or f"{page_size}/page".lower() in current_text:
                print(f"{page_label} size is already set to {page_size}.")
                return

        changer = page.locator(".ant-pagination-options-size-changer")
        changer.wait_for(state="visible", timeout=15000)
        changer.first.click()

        dropdown = page.locator(".ant-select-dropdown:visible")
        dropdown.wait_for(state="visible", timeout=15000)

        options = [
            page.locator(f".ant-select-dropdown:visible >> text=/\\b{page_size}\\b/"),
            page.locator(f"text={page_size} / page"),
            page.locator(f"text={page_size}/page"),
        ]

        clicked = False
        for opt in options:
            if opt.count() > 0:
                opt.first.click()
                clicked = True
                break

        if not clicked:
            raise RuntimeError(f"{page_size} option not found.")

        for _ in range(30):
            count = page.locator(row_sel).count()
            if count > 10 or page_size == 10:
                break
            page.wait_for_timeout(150)

        page.wait_for_timeout(500)
        dismiss_cookie_policy(page)
        print(f"{page_label} size is set to {page_size}.")

    except Exception as e:
        print(f"Could not set {page_label} size to {page_size} automatically: {e}")

def set_page_size_100(page: Page, row_sel: str = ROW_SEL, page_label: str = "page") -> None:
    _set_page_size(page, 100, row_sel, page_label)

def set_page_size_300(page: Page, row_sel: str = ROW_SEL, page_label: str = "page") -> None:
    _set_page_size(page, 300, row_sel, page_label)

def _extract_inverter_status_from_row(row_el) -> str:
    dot = row_el.query_selector("span.nco-pv-table-device-status-icon")
    if not dot:
        return "Unknown"

    title = (dot.get_attribute("title") or "").strip().lower()
    cls = (dot.get_attribute("class") or "").lower()

    if title in ("running", "normal"):
        return "Normal"
    if title in ("disconnected", "offline"):
        return "Offline"
    if title in ("idle", "standby"):
        return "Standby"
    if title in ("faulty", "alarm", "fault"):
        return "Faulty"

    if "green" in cls:
        return "Normal"
    if "gray" in cls or "grey" in cls:
        return "Offline"
    if "yellow" in cls:
        return "Standby"
    if "red" in cls:
        return "Faulty"

    return "Unknown"

def goto_inverter_list(page: Page) -> None:
    if not INVERTER_LIST_URL:
        raise RuntimeError("FUSIONSOLAR_INVERTER_LIST_URL is not set in .env")
    page.goto(INVERTER_LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    dismiss_cookie_policy(page)

def get_inverter_table_rows(page: Page):
    return page.locator(ROW_SEL)

def _get_inverter_table_body(page: Page):
    return page.locator(".ant-table-body").first

def _scroll_inverter_row_into_view(page: Page, row_index: int) -> None:
    body = _get_inverter_table_body(page)
    body.wait_for(state="visible", timeout=8000)

    row_height = 36
    target_top = max(0, row_index * row_height)

    page.evaluate(
        """({selector, top}) => {
            const el = document.querySelector(selector);
            if (el) {
                el.scrollTop = top;
            }
        }""",
        {"selector": ".ant-table-body", "top": target_top},
    )
    page.wait_for_timeout(220)

def extract_inverter_row_summary_by_index(page: Page, row_index: int) -> dict[str, str]:
    _scroll_inverter_row_into_view(page, row_index)

    row = get_inverter_table_rows(page).nth(row_index)
    tds = row.locator("td")

    values: list[str] = []
    for i in range(tds.count()):
        try:
            values.append(tds.nth(i).inner_text(timeout=600).strip())
        except Exception:
            values.append("")

    device_name = values[2] if len(values) > 2 else ""
    plant_name = values[3] if len(values) > 3 else ""
    device_sn = values[6] if len(values) > 6 else ""
    status = "Unknown"

    try:
        row_el = row.element_handle()
        if row_el:
            status = _extract_inverter_status_from_row(row_el)
    except Exception:
        status = "Unknown"

    return {
        "device_name": device_name,
        "plant_name": plant_name,
        "device_sn": device_sn,
        "status": status,
    }

def open_inverter_detail_in_new_tab_by_row_index(
    list_page: Page,
    context: BrowserContext,
    row_index: int,
) -> tuple[Page, dict[str, str]]:
    summary = extract_inverter_row_summary_by_index(list_page, row_index)

    last_error = None
    for _ in range(4):
        try:
            _scroll_inverter_row_into_view(list_page, row_index)
            dismiss_cookie_policy(list_page)

            row = get_inverter_table_rows(list_page).nth(row_index)
            link = row.locator("td:nth-child(3) a").first

            link.wait_for(state="visible", timeout=5000)

            href = link.get_attribute("href") or ""
            if not href:
                raise RuntimeError("Device detail link href is empty.")

            detail_url = urljoin(BASE + "/", href.lstrip("/"))

            detail_page = context.new_page()
            detail_page.goto(detail_url, wait_until="domcontentloaded")
            detail_page.wait_for_timeout(400)
            dismiss_cookie_policy(detail_page)

            return detail_page, summary

        except Exception as e:
            last_error = e
            try:
                for p in context.pages:
                    if p is not list_page and p.url == "about:blank":
                        p.close()
            except Exception:
                pass
            list_page.wait_for_timeout(250)

    raise RuntimeError(f"Could not open detail tab for row {row_index + 1}: {last_error}")

def go_to_next_table_page(page: Page) -> bool:
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

    btn = next_li.locator("button.ant-pagination-item-link").first
    btn.wait_for(state="visible", timeout=5000)

    try:
        btn.click(timeout=5000, no_wait_after=True)
    except Exception:
        dismiss_cookie_policy(page)
        try:
            btn.click(timeout=3000, no_wait_after=True, force=True)
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

    try:
        page.evaluate(
            """() => {
                const el = document.querySelector('.ant-table-body');
                if (el) el.scrollTop = 0;
            }"""
        )
    except Exception:
        pass

    page.wait_for_timeout(700)
    dismiss_cookie_policy(page)
    return True

def filter_by_sn_and_open(page: Page, device_sn: str) -> bool:
    dismiss_cookie_policy(page)

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

    sn_input.click()
    sn_input.fill("")
    sn_input.type(device_sn, delay=20)

    filter_bar = page.locator("div:has(input[placeholder='SN'])")
    if filter_bar.count() == 0:
        filter_bar = page.locator("form")

    search_btn = filter_bar.get_by_role("button", name="Search")
    if search_btn.count() == 0:
        search_btn = filter_bar.locator("button.ant-btn-primary")

    search_btn.first.click()
    page.wait_for_timeout(800)
    page.wait_for_selector(ROW_SEL, timeout=15000)

    first_row = page.locator(ROW_SEL).first
    if first_row.count() == 0:
        return False

    cell_link = first_row.locator("td:nth-child(3) a")
    if cell_link.count() > 0:
        for _ in range(3):
            try:
                dismiss_cookie_policy(page)
                cell_link = page.locator(ROW_SEL).first.locator("td:nth-child(3) a").first
                cell_link.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(150)
                cell_link.click(timeout=6000, no_wait_after=True)
                page.wait_for_timeout(500)
                return True
            except Exception:
                page.wait_for_timeout(300)

        raise RuntimeError(f"Could not click filtered inverter row for SN {device_sn}")

    first_row.locator("td:nth-child(3)").click(timeout=6000, no_wait_after=True)
    page.wait_for_timeout(500)
    return True

def _clean_number(value: str) -> float | None:
    if not value:
        return None
    value = value.replace("°C", "").replace("℃", "").replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None

def scrape_inverter_detail_temperature_fast(page: Page) -> float | None:
    candidate_roots = [
        page.locator("div.nco-realtime-info-signal-wrapper"),
        page.locator("div:has-text('Real-Time Device Data')"),
        page.locator("body"),
    ]

    labels = [
        "Internal Temperature",
        "Internal temperature",
        "Device Internal Temperature",
        "Cabinet Temperature",
        "Inside Temperature",
    ]

    for root in candidate_roots:
        try:
            if root.count() == 0:
                continue

            root.first.wait_for(state="visible", timeout=8000)

            for label in labels:
                locs = root.first.locator(f"text={label}")
                if locs.count() == 0:
                    continue

                for i in range(min(locs.count(), 5)):
                    try:
                        label_loc = locs.nth(i)
                        container_text = label_loc.locator(
                            "xpath=ancestor::*[self::div or self::span][1]"
                        ).inner_text(timeout=400)
                        value = _clean_number(container_text)
                        if value is not None:
                            return value
                    except Exception:
                        pass

                    try:
                        sibling_text = label_loc.locator("xpath=following::*[1]").inner_text(timeout=400)
                        value = _clean_number(sibling_text)
                        if value is not None:
                            return value
                    except Exception:
                        pass
        except Exception:
            continue

    return None

def scrape_inverter_detail_telemetry(page: Page) -> dict:
    fast_temp = scrape_inverter_detail_temperature_fast(page)
    if fast_temp is not None:
        return {"internal_temperature_c": fast_temp}

    wrapper = page.locator("div.nco-realtime-info-signal-wrapper")
    wrapper.wait_for(state="visible", timeout=15000)

    pairs: dict[str, str] = {}

    pv_rows = wrapper.locator(
        "table tbody.ant-table-tbody tr.ant-table-row:not(.ant-table-measure-row)"
    )
    for i in range(pv_rows.count()):
        tr = pv_rows.nth(i)
        tds = tr.locator("td")
        if tds.count() >= 5:
            row_label = tds.nth(0).inner_text().strip()
            pv1 = tds.nth(1).inner_text().strip()
            pv2 = tds.nth(2).inner_text().strip()
            pv3 = tds.nth(3).inner_text().strip()
            pv4 = tds.nth(4).inner_text().strip()

            pairs[f"{row_label}|PV1"] = pv1
            pairs[f"{row_label}|PV2"] = pv2
            pairs[f"{row_label}|PV3"] = pv3
            pairs[f"{row_label}|PV4"] = pv4

    blocks = wrapper.locator("div.ant-col")
    texts = []
    for i in range(blocks.count()):
        t = blocks.nth(i).inner_text().strip()
        if t and t not in ("•",):
            texts.append(t)

    for i in range(0, len(texts) - 1, 2):
        label = texts[i]
        value = texts[i + 1]
        if label.startswith("Input Voltage") or label.startswith("Input Current"):
            continue
        pairs[label] = value

    telemetry = parse_realtime_kv(pairs)
    return telemetry