from __future__ import annotations
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from app.services.playwright_client import (
    create_fusionsolar_context,
    dismiss_cookie_policy,
)

load_dotenv()

BASE_URL = os.getenv("FUSIONSOLAR_BASE_URL", "https://intl.fusionsolar.huawei.com")
HOME_URL = os.getenv("FUSIONSOLAR_HOME_URL")
STATE_FILE = os.getenv("FUSIONSOLAR_STATE_FILE", "fusionsolar_state.json")
PLANT_TABLE_ROW_SELECTOR = "tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)"
LOW_PSH_ABSOLUTE_THRESHOLD = Decimal(os.getenv("LOW_PSH_ABSOLUTE_THRESHOLD", "3"))

@dataclass(slots=True)
class PlantPerformance:
    status: str | None
    plant_name: str
    country: str | None
    grid_connection_date: str | None
    total_string_capacity_kwp: Decimal | None
    current_power_kw: Decimal | None
    specific_energy_kwh_kwp: Decimal | None
    yield_today_kwh: Decimal | None
    total_yield_kwh: Decimal | None

    @property
    def psh(self) -> Decimal | None:
        if self.specific_energy_kwh_kwp is not None:
            return self.specific_energy_kwh_kwp

        if self.yield_today_kwh is None or self.total_string_capacity_kwp in (
            None,
            Decimal("0"),
        ):
            return None

        return (self.yield_today_kwh / self.total_string_capacity_kwp).quantize(
            Decimal("0.001")
        )

def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text or text == "--":
        return None

    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))

    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None

def _safe_text(values: list[str], index: int) -> str | None:
    if index >= len(values):
        return None

    text = values[index].strip()

    if not text or text == "--":
        return None

    return text

def _extract_status_from_row(row_el) -> str | None:
    try:
        icon = row_el.query_selector("div.nco-station-state-circle")

        if not icon:
            return None

        cls = (icon.get_attribute("class") or "").lower()

        if "nco-station-state-green-circle" in cls:
            return "Normal"

        if "nco-station-state-grey-circle" in cls:
            return "Offline"

        if "nco-station-state-yellow-circle" in cls:
            return "Standby"

        if "nco-station-state-red-circle" in cls:
            return "Faulty"

    except Exception:
        pass

    return None

def _parse_plant_row(
    values: list[str],
    detected_status: str | None,
) -> PlantPerformance | None:
    plant_name = _safe_text(values, 2)

    if not plant_name:
        return None

    return PlantPerformance(
        status=detected_status or "Unknown",
        plant_name=plant_name,
        country=_safe_text(values, 3),
        grid_connection_date=_safe_text(values, 4),
        total_string_capacity_kwp=_to_decimal(_safe_text(values, 5)),
        current_power_kw=_to_decimal(_safe_text(values, 8)),
        specific_energy_kwh_kwp=_to_decimal(_safe_text(values, 9)),
        yield_today_kwh=_to_decimal(_safe_text(values, 10)),
        total_yield_kwh=_to_decimal(_safe_text(values, 11)),
    )

def _set_page_size_100(page: Page) -> None:
    try:
        dismiss_cookie_policy(page)

        changer = page.locator(".ant-pagination-options-size-changer")

        if changer.count() == 0:
            return

        current_label = page.locator(".ant-pagination-options .ant-select-selection-item")

        if current_label.count() > 0:
            current_text = (current_label.first.inner_text() or "").strip().lower()

            if "100 / page" in current_text or "100/page" in current_text:
                return

        changer.first.click()
        page.wait_for_timeout(250)

        options = [
            page.locator(".ant-select-dropdown:visible >> text=/\\b100\\b/"),
            page.locator("text=100 / page"),
            page.locator("text=100/page"),
        ]

        for option in options:
            if option.count() > 0:
                option.first.click()
                break

        for _ in range(40):
            if page.locator(PLANT_TABLE_ROW_SELECTOR).count() >= 50:
                break

            page.wait_for_timeout(250)

        dismiss_cookie_policy(page)

    except Exception:
        return

def _go_to_plant_list(page: Page) -> None:
    target = HOME_URL or BASE_URL
    page.goto(target, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    dismiss_cookie_policy(page)

    if "login/build/index.html" in page.url:
        print("Please login to FusionSolar in the browser window...")

        page.wait_for_function(
            "(() => !window.location.href.includes('/pvmswebsite/login/build/index.html'))()",
            timeout=180000,
        )

    if "#/home/list" not in page.url:
        base_no_hash = page.url.split("#", 1)[0]
        page.goto(f"{base_no_hash}#/home/list", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        dismiss_cookie_policy(page)

    page.wait_for_selector(PLANT_TABLE_ROW_SELECTOR, timeout=60000)
    dismiss_cookie_policy(page)

    _set_page_size_100(page)

    page.wait_for_selector(PLANT_TABLE_ROW_SELECTOR, timeout=60000)
    dismiss_cookie_policy(page)

def _go_to_next_plant_page(page: Page) -> bool:
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
        active_before = (
            page.locator("li.ant-pagination-item-active").first.inner_text().strip()
        )
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
    return True

def fetch_plants_from_fusionsolar(
    max_pages: int = 20,
    headless: bool = False,
) -> list[PlantPerformance]:
    plants: list[PlantPerformance] = []
    seen_names: set[str] = set()

    state_path = Path(STATE_FILE)

    with sync_playwright() as p:
        browser, context = create_fusionsolar_context(p, headless=headless)
        page = context.new_page()

        _go_to_plant_list(page)
        context.storage_state(path=str(state_path))

        def scrape_current_page() -> int:
            dismiss_cookie_policy(page)

            rows = page.query_selector_all(PLANT_TABLE_ROW_SELECTOR)
            added = 0

            for row in rows:
                values = [
                    td.inner_text().strip()
                    for td in row.query_selector_all("td")
                ]

                if not any(values):
                    continue

                detected_status = _extract_status_from_row(row)
                perf = _parse_plant_row(values, detected_status)

                if perf is None or perf.plant_name in seen_names:
                    continue

                seen_names.add(perf.plant_name)
                plants.append(perf)
                added += 1

            return added

        added = scrape_current_page()
        print(f"Fetched {added} plants from page 1")

        for page_no in range(2, max_pages + 1):
            moved = _go_to_next_plant_page(page)

            if not moved:
                break

            page.wait_for_selector(PLANT_TABLE_ROW_SELECTOR, timeout=60000)
            dismiss_cookie_policy(page)

            added = scrape_current_page()
            print(f"Fetched {added} plants from page {page_no}")

            if added == 0:
                break

        browser.close()

    return plants

def load_city_mapping_from_excel(
    excel_path: str | os.PathLike[str],
) -> pd.DataFrame:
    df = pd.read_excel(excel_path)
    required = {"City", "Plant Name"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Excel file is missing required columns: {sorted(missing)}")

    mapping = (
        df[["Plant Name", "City"]]
        .dropna(subset=["Plant Name", "City"])
        .assign(
            **{
                "Plant Name": lambda x: x["Plant Name"].astype(str).str.strip(),
                "City": lambda x: x["City"].astype(str).str.strip(),
            }
        )
        .drop_duplicates(subset=["Plant Name"])
    )

    return mapping

def build_city_low_psh_report(
    plant_rows: Iterable[PlantPerformance],
    city_mapping_df: pd.DataFrame,
    underperformance_pct: Decimal | float = Decimal("10"),
    absolute_psh_threshold: Decimal | float = LOW_PSH_ABSOLUTE_THRESHOLD,
) -> pd.DataFrame:
    rows = []

    for plant in plant_rows:
        rows.append(
            {
                "plant_name": plant.plant_name,
                "status": plant.status,
                "country": plant.country,
                "grid_connection_date": plant.grid_connection_date,
                "total_string_capacity_kwp": (
                    float(plant.total_string_capacity_kwp)
                    if plant.total_string_capacity_kwp is not None
                    else None
                ),
                "current_power_kw": (
                    float(plant.current_power_kw)
                    if plant.current_power_kw is not None
                    else None
                ),
                "specific_energy_kwh_kwp": (
                    float(plant.specific_energy_kwh_kwp)
                    if plant.specific_energy_kwh_kwp is not None
                    else None
                ),
                "yield_today_kwh": (
                    float(plant.yield_today_kwh)
                    if plant.yield_today_kwh is not None
                    else None
                ),
                "total_yield_kwh": (
                    float(plant.total_yield_kwh)
                    if plant.total_yield_kwh is not None
                    else None
                ),
                "psh": float(plant.psh) if plant.psh is not None else None,
            }
        )

    performance_df = pd.DataFrame(rows)

    if performance_df.empty:
        return performance_df

    mapping_df = city_mapping_df.rename(
        columns={
            "Plant Name": "plant_name",
            "City": "city",
        }
    ).copy()

    merged = performance_df.merge(
        mapping_df,
        on="plant_name",
        how="left",
        validate="one_to_one",
    )

    unmapped = sorted(
        merged.loc[merged["city"].isna(), "plant_name"].dropna().unique().tolist()
    )

    if unmapped:
        raise ValueError(
            "These FusionSolar plants do not exist in the Excel city mapping: "
            + ", ".join(unmapped[:20])
            + (" ..." if len(unmapped) > 20 else "")
        )

    merged["psh"] = pd.to_numeric(merged["psh"], errors="coerce")

    valid_psh = merged[merged["psh"].notna()].copy()

    valid_psh["city_plant_count"] = valid_psh.groupby("city")[
        "plant_name"
    ].transform("count")

    valid_psh["city_avg_psh"] = valid_psh.groupby("city")["psh"].transform("mean")

    threshold_factor = Decimal("1") - (
        Decimal(str(underperformance_pct)) / Decimal("100")
    )

    absolute_psh_threshold_float = float(Decimal(str(absolute_psh_threshold)))

    valid_psh["threshold_psh"] = (
        valid_psh["city_avg_psh"] * float(threshold_factor)
    )

    valid_psh["below_city_threshold"] = (
        (valid_psh["city_plant_count"] > 1)
        & (valid_psh["psh"] < valid_psh["threshold_psh"])
    )

    valid_psh["below_absolute_psh_threshold"] = (
        valid_psh["psh"] < absolute_psh_threshold_float
    )

    def classify(row: pd.Series) -> str:
        if bool(row["below_city_threshold"]) or bool(row["below_absolute_psh_threshold"]):
            return "Underperforming"

        if row["city_plant_count"] <= 1:
            return "No comparison required"

        return "Normal"

    valid_psh["performance_status"] = valid_psh.apply(classify, axis=1)

    valid_psh["psh_deviation_pct_vs_city_avg"] = (
        (
            (valid_psh["psh"] - valid_psh["city_avg_psh"])
            / valid_psh["city_avg_psh"]
        )
        * 100
    ).round(2)

    valid_psh["underperforming"] = valid_psh["performance_status"].eq(
        "Underperforming"
    )

    missing_psh = merged[merged["psh"].isna()].copy()

    if not missing_psh.empty:
        missing_psh["city_plant_count"] = None
        missing_psh["city_avg_psh"] = None
        missing_psh["threshold_psh"] = None
        missing_psh["below_city_threshold"] = False
        missing_psh["below_absolute_psh_threshold"] = False
        missing_psh["performance_status"] = "PSH Missing"
        missing_psh["psh_deviation_pct_vs_city_avg"] = None
        missing_psh["underperforming"] = False

        valid_psh = pd.concat(
            [valid_psh, missing_psh],
            ignore_index=True,
            sort=False,
        )

    return valid_psh.sort_values(
        ["city", "plant_name"],
        kind="stable",
    ).reset_index(drop=True)

def fetch_and_detect_low_psh_by_city(
    excel_path: str | os.PathLike[str],
    *,
    underperformance_pct: Decimal | float = Decimal("10"),
    absolute_psh_threshold: Decimal | float = LOW_PSH_ABSOLUTE_THRESHOLD,
    max_pages: int = 20,
    headless: bool = False,
) -> pd.DataFrame:
    city_mapping_df = load_city_mapping_from_excel(excel_path)
    plants = fetch_plants_from_fusionsolar(
        max_pages=max_pages,
        headless=headless,
    )

    return build_city_low_psh_report(
        plant_rows=plants,
        city_mapping_df=city_mapping_df,
        underperformance_pct=underperformance_pct,
        absolute_psh_threshold=absolute_psh_threshold,
    )