from __future__ import annotations
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.playwright_client import (
    create_fusionsolar_context,
    dismiss_cookie_policy,
    open_fusionsolar_target,
)
from app.services.report_path_service import EXCEL_PLANTS_DIR
from app.utils.time_utils import today_gmt8

load_dotenv()

FUSIONSOLAR_STATION_LIST_URL = os.getenv(
    "FUSIONSOLAR_STATION_LIST_URL",
    "https://intl.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-7-5c65c6ee-49c2-4032-ae36-222b03f97b37#/view/station",
)
LOW_PSH_REPORT_DIR = Path(os.getenv("LOW_PSH_REPORT_DIR", str(EXCEL_PLANTS_DIR)))
LOW_PSH_REPORT_PATTERN = os.getenv("LOW_PSH_REPORT_PATTERN", "low_psh_plants_report_*.xlsx")
INVERTER_THRESHOLD_PCT = Decimal(os.getenv("LOW_INVERTER_PSH_THRESHOLD_PCT", "10"))
INVERTER_REPORT_ROW_SELECTOR = (
    "tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row), "
    "tbody.dpdesign-table-tbody > tr.dpdesign-table-row:not(.dpdesign-table-measure-row)"
)

@dataclass(slots=True)
class LowPshPlant:
    plant_name: str
    city: str | None = None
    plant_status: str | None = None
    plant_psh: Decimal | None = None
    city_avg_psh: Decimal | None = None

@dataclass(slots=True)
class InverterReportRow:
    plant_name: str
    inverter_name: str
    inverter_sn: str | None
    total_string_capacity_kwp: Decimal | None
    yield_kwh: Decimal | None
    total_yield_kwh: Decimal | None
    specific_energy_kwh_kwp: Decimal | None

@dataclass(slots=True)
class LowPerformingInverterResult:
    run_day: date
    plant_name: str
    city: str | None
    plant_status: str | None
    plant_psh: Decimal | None
    city_avg_psh: Decimal | None
    inverter_name: str
    inverter_sn: str | None
    inverter_psh: Decimal
    benchmark_inverter_psh: Decimal
    threshold_inverter_psh: Decimal
    deviation_pct_vs_benchmark: Decimal
    underperforming: bool
    reason: str

def _normalise_col_name(value: str) -> str:
    text_value = str(value or "").strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", "_", text_value)
    return text_value.strip("_")

def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None

    text_value = str(value).strip()
    if not text_value or text_value == "--":
        return None

    cleaned = re.sub(r"[^\d.\-]", "", text_value.replace(",", ""))
    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None

def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None

def _is_truthy(value) -> bool:
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
        "underperforming",
    }

def find_latest_low_psh_report(
    report_dir: str | Path = LOW_PSH_REPORT_DIR,
    pattern: str = LOW_PSH_REPORT_PATTERN,
) -> Path:
    report_dir = Path(report_dir)
    files = sorted(report_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    if not files:
        raise FileNotFoundError(
            f"No low PSH report found in '{report_dir}' using pattern '{pattern}'. "
            "Run detect_low_psh_plants_by_city first."
        )

    return files[0]

def load_underperforming_plants_from_low_psh_report(report_path: str | Path) -> list[LowPshPlant]:
    report_path = Path(report_path)
    df = pd.read_excel(report_path)
    df.columns = [_normalise_col_name(c) for c in df.columns]

    required = {"plant_name", "underperforming"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Low PSH report is missing required columns: {sorted(missing)}")

    under_df = df[df["underperforming"].apply(_is_truthy)].copy()
    plants: list[LowPshPlant] = []

    for _, row in under_df.iterrows():
        plant_name = str(row.get("plant_name") or "").strip()

        if not plant_name:
            continue

        plants.append(
            LowPshPlant(
                plant_name=plant_name,
                city=str(row.get("city") or "").strip() or None,
                plant_status=str(row.get("status") or "").strip() or None,
                plant_psh=_to_decimal(row.get("psh")),
                city_avg_psh=_to_decimal(row.get("city_avg_psh")),
            )
        )

    return plants

def fetch_latest_underperforming_plants_from_db(db: Session) -> list[LowPshPlant]:
    rows = (
        db.execute(
            text(
                """
                SELECT plant_name, city, performance_status, psh, city_avg_psh
                FROM low_psh_plants_by_city_latest
                WHERE run_day = (
                    SELECT MAX(run_day)
                    FROM low_psh_plants_by_city_latest
                )
                  AND underperforming = true
                ORDER BY plant_name ASC
                """
            )
        )
        .mappings()
        .all()
    )

    return [
        LowPshPlant(
            plant_name=str(r["plant_name"]).strip(),
            city=r.get("city"),
            plant_status=r.get("performance_status"),
            plant_psh=_to_decimal(r.get("psh")),
            city_avg_psh=_to_decimal(r.get("city_avg_psh")),
        )
        for r in rows
        if r.get("plant_name")
    ]

def load_underperforming_plants_for_inverter_check(
    db: Session,
    *,
    prefer_excel: bool = True,
    report_path: str | Path | None = None,
) -> list[LowPshPlant]:
    if prefer_excel:
        selected_report = Path(report_path) if report_path else find_latest_low_psh_report()
        return load_underperforming_plants_from_low_psh_report(selected_report)

    plants = fetch_latest_underperforming_plants_from_db(db)

    if plants:
        return plants

    selected_report = Path(report_path) if report_path else find_latest_low_psh_report()
    return load_underperforming_plants_from_low_psh_report(selected_report)

def _click_first_visible(page: Page, selectors: Iterable[str], *, timeout: int = 10000) -> None:
    last_error: Exception | None = None

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()

            if count == 0:
                continue

            for idx in range(count):
                item = locator.nth(idx)

                try:
                    if not item.is_visible(timeout=800):
                        continue

                    item.scroll_into_view_if_needed(timeout=3000)
                    dismiss_cookie_policy(page)
                    item.click(timeout=timeout, no_wait_after=True)
                    page.wait_for_timeout(700)
                    dismiss_cookie_policy(page)
                    return

                except Exception as exc:
                    last_error = exc
                    continue

        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Could not click any selector: {list(selectors)}. Last error: {last_error}")

def _compact_name(value: str | None) -> str:
    text_value = str(value or "").replace("\u00a0", " ")
    text_value = text_value.replace("…", " ").replace("...", " ")
    text_value = re.sub(r"[^A-Za-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip().upper()

def _search_terms_for_plant(plant_name: str) -> list[str]:
    raw = re.sub(r"\s+", " ", str(plant_name or "").strip())
    no_parentheses = re.sub(r"\([^)]*\)", " ", raw)
    no_punctuation = re.sub(r"[^A-Za-z0-9]+", " ", no_parentheses)
    tokens = [t for t in no_punctuation.split() if t]

    candidate_terms = [
        raw,
        no_parentheses.strip(),
        " ".join(tokens[:6]),
        " ".join(tokens[:5]),
        " ".join(tokens[:4]),
        " ".join(tokens[:3]),
        " ".join(tokens[:2]),
    ]

    terms: list[str] = []

    for term in candidate_terms:
        term = re.sub(r"\s+", " ", term).strip()

        if len(term) >= 3 and term.upper() not in {t.upper() for t in terms}:
            terms.append(term)

    return terms

def _station_tree_node_count(page: Page) -> int:
    try:
        return page.locator("span.node-name").count()
    except Exception:
        return 0

def _click_more_until_loaded(page: Page, *, max_clicks: int = 100) -> int:
    clicks = 0

    for _ in range(max_clicks):
        dismiss_cookie_policy(page)

        more_links = page.locator(
            "li.flex-node-line a",
            has_text=re.compile(r"^\s*More\s*$", re.I),
        )

        if more_links.count() == 0:
            more_links = page.locator(
                "a",
                has_text=re.compile(r"^\s*More\s*$", re.I),
            )

        visible_index: int | None = None

        for idx in range(more_links.count()):
            try:
                if more_links.nth(idx).is_visible(timeout=300):
                    visible_index = idx
                    break
            except Exception:
                continue

        if visible_index is None:
            break

        before = _station_tree_node_count(page)

        try:
            more_links.nth(visible_index).scroll_into_view_if_needed(timeout=3000)
            more_links.nth(visible_index).click(timeout=5000, no_wait_after=True)

            clicks += 1
            page.wait_for_timeout(1200)

            after = _station_tree_node_count(page)

            if after <= before:
                page.wait_for_timeout(1200)

                if _station_tree_node_count(page) <= before:
                    break

        except Exception:
            break

    return clicks

def _clear_station_tree_search(page: Page) -> None:
    search_inputs = [
        "input[placeholder='Enter a device name']",
        "input[placeholder*='device' i]",
        ".tree-searcher input",
        ".search-input input",
        ".ant-input-affix-wrapper input",
    ]

    for selector in search_inputs:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            target = loc.first

            if not target.is_visible(timeout=500):
                continue

            target.click(timeout=2000)
            target.fill("")
            target.press("Enter")
            page.wait_for_timeout(1000)
            return

        except Exception:
            continue

def _search_station_tree(page: Page, term: str) -> bool:
    search_inputs = [
        "input[placeholder='Enter a device name']",
        "input[placeholder*='device' i]",
        ".tree-searcher input",
        ".search-input input",
        ".ant-input-affix-wrapper input",
    ]

    for selector in search_inputs:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            target = loc.first
            target.wait_for(state="visible", timeout=5000)
            target.click(timeout=3000)
            target.fill("")
            target.type(term, delay=20)
            target.press("Enter")

            page.wait_for_timeout(2000)
            dismiss_cookie_policy(page)

            return True

        except Exception:
            continue

    return False

def _mark_best_station_node_match(page: Page, plant_name: str) -> dict:
    return page.evaluate(
        r"""
        (plantName) => {
            const normalise = (text) => (text || '')
                .replace(/\u00a0/g, ' ')
                .replace(/[.…]+/g, ' ')
                .replace(/[^A-Za-z0-9]+/g, ' ')
                .replace(/\s+/g, ' ')
                .trim()
                .toUpperCase();

            const tokenise = (text) => normalise(text).split(' ').filter(Boolean);

            const wanted = normalise(plantName);
            const wantedTokens = tokenise(plantName);

            document.querySelectorAll('[data-spms-plant-match="true"]').forEach((node) => {
                node.removeAttribute('data-spms-plant-match');
            });

            const nodes = Array.from(document.querySelectorAll('span.node-name'));
            let best = null;

            for (const node of nodes) {
                const parentTitle =
                    node.closest('[title]')?.getAttribute('title') ||
                    node.parentElement?.getAttribute('title') ||
                    '';

                const rawText =
                    node.getAttribute('title') ||
                    parentTitle ||
                    node.textContent ||
                    node.innerText ||
                    '';

                const displayText = node.innerText || rawText;
                const candidate = normalise(rawText);
                const candidateTokens = tokenise(rawText);

                let score = 0;

                if (candidate === wanted) {
                    score = 1000;
                } else if (candidate.includes(wanted) || wanted.includes(candidate)) {
                    score = 850 + Math.min(candidate.length, wanted.length) / Math.max(candidate.length, wanted.length || 1);
                } else {
                    const candidateSet = new Set(candidateTokens);
                    const hits = wantedTokens.filter((token) => candidateSet.has(token)).length;
                    const ratio = wantedTokens.length ? hits / wantedTokens.length : 0;

                    score = ratio * 700;

                    const firstWanted = wantedTokens.slice(0, 3).join(' ');
                    const firstCandidate = candidateTokens.slice(0, 3).join(' ');

                    if (firstWanted && firstWanted === firstCandidate) {
                        score += 120;
                    }
                }

                const rect = node.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;

                if (!visible) {
                    score -= 50;
                }

                if (!best || score > best.score) {
                    best = {
                        node,
                        score,
                        rawText,
                        displayText,
                        candidate,
                    };
                }
            }

            if (!best || best.score < 360) {
                return {
                    matched: false,
                    wanted,
                    bestText: best ? best.rawText : null,
                    bestDisplayText: best ? best.displayText : null,
                    bestScore: best ? best.score : 0,
                    nodeCount: nodes.length,
                };
            }

            best.node.setAttribute('data-spms-plant-match', 'true');

            return {
                matched: true,
                wanted,
                matchedText: best.rawText,
                matchedDisplayText: best.displayText,
                score: best.score,
                nodeCount: nodes.length,
            };
        }
        """,
        plant_name,
    )

def _click_marked_station_node(page: Page) -> None:
    target = page.locator("span.node-name[data-spms-plant-match='true']").first
    target.wait_for(state="visible", timeout=10000)
    target.scroll_into_view_if_needed(timeout=5000)

    dismiss_cookie_policy(page)
    target.click(timeout=10000, no_wait_after=True)

    page.wait_for_timeout(1800)
    dismiss_cookie_policy(page)

def _click_plant_in_tree(page: Page, plant_name: str) -> None:
    dismiss_cookie_policy(page)
    page.wait_for_selector("span.node-name, input[placeholder*='device' i]", timeout=30000)

    attempts: list[str] = []
    last_match: dict | None = None

    match = _mark_best_station_node_match(page, plant_name)
    last_match = match

    if match.get("matched"):
        print(f"  Matched plant: {match.get('matchedText')} | score={match.get('score'):.2f}")
        _click_marked_station_node(page)
        return

    for term in _search_terms_for_plant(plant_name):
        attempts.append(f"search:{term}")

        if _search_station_tree(page, term):
            _click_more_until_loaded(page, max_clicks=20)

            match = _mark_best_station_node_match(page, plant_name)
            last_match = match

            if match.get("matched"):
                print(
                    f"  Matched plant: {match.get('matchedText')} | "
                    f"score={match.get('score'):.2f} | search='{term}'"
                )
                _click_marked_station_node(page)
                return

    attempts.append("clear-search")
    _clear_station_tree_search(page)
    page.wait_for_timeout(800)

    more_clicks = _click_more_until_loaded(page, max_clicks=100)
    attempts.append(f"clicked-more:{more_clicks}")

    match = _mark_best_station_node_match(page, plant_name)
    last_match = match

    if match.get("matched"):
        print(
            f"  Matched plant: {match.get('matchedText')} | "
            f"score={match.get('score'):.2f} | after More"
        )
        _click_marked_station_node(page)
        return

    raise RuntimeError(
        f"Could not find or click plant '{plant_name}' in FusionSolar station tree. "
        f"Attempts: {attempts}. "
        f"Loaded nodes: {last_match.get('nodeCount') if last_match else 'unknown'}. "
        f"Best visible match: {last_match.get('bestText') if last_match else None}. "
        f"Best score: {last_match.get('bestScore') if last_match else None}."
    )

def _open_report_management(page: Page) -> None:
    _click_first_visible(
        page,
        [
            "span.monitor-tab[title='Report Management'] a",
            "span.monitor-tab:has-text('Report Management') a",
            "a:has-text('Report Management')",
            "xpath=//a[normalize-space()='Report Management']",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(1200)

def _open_inverter_report_tab(page: Page) -> None:
    try:
        active_tab = page.locator(
            "div[role='tab'][aria-selected='true']",
            has_text=re.compile(r"Inverter Report", re.I),
        )

        if active_tab.count() > 0 and active_tab.first.is_visible(timeout=1000):
            return

    except Exception:
        pass

    _click_first_visible(
        page,
        [
            "div[role='tab']:has-text('Inverter Report')",
            "div.ant-tabs-tab-btn:has-text('Inverter Report')",
            "xpath=//div[@role='tab' and normalize-space()='Inverter Report']",
            "text=Inverter Report",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(1200)

def _set_report_date_if_possible(page: Page, report_day: date | None) -> None:
    if not report_day:
        return

    date_text = report_day.strftime("%Y-%m-%d")

    candidates = [
        "input#statisticTime",
        "input[placeholder='Select date']",
        "input[title][value]",
        ".dpdesign-picker-input input",
        ".ant-picker input",
    ]

    for selector in candidates:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            target = loc.first

            if not target.is_visible(timeout=800):
                continue

            target.click(timeout=3000)
            target.fill("")
            target.type(date_text, delay=20)
            target.press("Enter")

            page.wait_for_timeout(800)
            dismiss_cookie_policy(page)
            return

        except Exception:
            continue

def _click_search_if_possible(page: Page) -> None:
    search_selectors = [
        ".nco-inverter-report button.dpdesign-btn-primary:has-text('Search')",
        ".nco-report-container button.dpdesign-btn-primary:has-text('Search')",
        ".nco-inverter-search-bar button:has-text('Search')",
        "button[type='button'].dpdesign-btn-primary:has-text('Search')",
        "button[type='submit'].ant-btn-primary:has-text('Search')",
        "xpath=//div[contains(@class, 'nco-inverter-report')]//button[.//span[normalize-space()='Search'] or normalize-space()='Search']",
    ]

    for selector in search_selectors:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            for idx in range(loc.count()):
                button = loc.nth(idx)

                if not button.is_visible(timeout=800):
                    continue

                button.scroll_into_view_if_needed(timeout=3000)
                dismiss_cookie_policy(page)
                button.click(timeout=5000, no_wait_after=True)

                page.wait_for_timeout(2000)
                dismiss_cookie_policy(page)
                return

        except Exception:
            continue

def _wait_for_inverter_report_table(page: Page) -> None:
    page.wait_for_function(
        r"""
        () => {
            const normalise = (text) => (text || '').replace(/\s+/g, ' ').trim().toLowerCase();

            const wrappers = Array.from(document.querySelectorAll(
                '.dpdesign-table, .dpdesign-table-wrapper, .ant-table, .ant-table-wrapper'
            ));

            for (const wrapper of wrappers) {
                const rect = wrapper.getBoundingClientRect();

                if (rect.width === 0 || rect.height === 0) {
                    continue;
                }

                const headers = Array.from(wrapper.querySelectorAll('thead th'))
                    .map((th) => normalise(th.innerText))
                    .filter(Boolean);

                const headerText = headers.join(' | ');

                const hasInverterHeaders =
                    headerText.includes('device name') &&
                    headerText.includes('specific energy');

                if (!hasInverterHeaders) {
                    continue;
                }

                const rows = wrapper.querySelectorAll(
                    'tbody.dpdesign-table-tbody > tr.dpdesign-table-row:not(.dpdesign-table-measure-row), ' +
                    'tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)'
                );

                if (rows.length > 0) {
                    return true;
                }
            }

            return false;
        }
        """,
        timeout=30000,
    )

    page.wait_for_timeout(500)

def _extract_current_inverter_table_page(page: Page) -> list[dict]:
    _wait_for_inverter_report_table(page)

    return page.evaluate(
        r"""
        () => {
            const normalise = (text) => (text || '').replace(/\s+/g, ' ').trim();

            const wrappers = Array.from(document.querySelectorAll(
                '.dpdesign-table, .dpdesign-table-wrapper, .ant-table, .ant-table-wrapper'
            ));

            const parsedRows = [];

            for (const wrapper of wrappers) {
                const rect = wrapper.getBoundingClientRect();

                if (rect.width === 0 || rect.height === 0) {
                    continue;
                }

                const headers = Array.from(wrapper.querySelectorAll('thead th'))
                    .map((th) => normalise(th.innerText))
                    .filter((h) => h && h !== '\u00a0');

                const headerText = headers.join(' | ').toLowerCase();

                if (!headerText.includes('specific energy') || !headerText.includes('device name')) {
                    continue;
                }

                const bodyRows = Array.from(wrapper.querySelectorAll(
                    'tbody.dpdesign-table-tbody > tr.dpdesign-table-row:not(.dpdesign-table-measure-row), ' +
                    'tbody.ant-table-tbody > tr.ant-table-row:not(.ant-table-measure-row)'
                ));

                for (const tr of bodyRows) {
                    const cells = Array.from(tr.querySelectorAll('td')).map((td) => normalise(td.innerText));
                    const rowKey = tr.getAttribute('data-row-key') || '';

                    if (cells.some(Boolean)) {
                        parsedRows.push({
                            headers,
                            cells,
                            rowKey,
                        });
                    }
                }
            }

            return parsedRows;
        }
        """
    )

def _click_next_inverter_report_page_if_possible(page: Page) -> bool:
    return bool(
        page.evaluate(
            r"""
            () => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const candidates = Array.from(document.querySelectorAll(
                    'li.dpdesign-pagination-next, li.ant-pagination-next'
                ));

                for (const li of candidates) {
                    if (!isVisible(li)) {
                        continue;
                    }

                    const ariaDisabled = li.getAttribute('aria-disabled') === 'true';
                    const classText = li.className || '';
                    const disabledByClass =
                        classText.includes('disabled') ||
                        classText.includes('pagination-disabled');

                    if (ariaDisabled || disabledByClass) {
                        continue;
                    }

                    const button = li.querySelector('button, a') || li;

                    if (!button || button.disabled) {
                        continue;
                    }

                    button.click();
                    return true;
                }

                return false;
            }
            """
        )
    )

def _extract_inverter_report_rows_from_table(page: Page) -> list[dict]:
    all_rows: list[dict] = []
    seen_keys: set[str] = set()

    for page_no in range(1, 51):
        current_rows = _extract_current_inverter_table_page(page)

        for row in current_rows:
            cells = row.get("cells") or []
            row_key = str(row.get("rowKey") or "").strip()
            identity = row_key or "|".join(str(cell) for cell in cells)

            if identity in seen_keys:
                continue

            seen_keys.add(identity)
            all_rows.append(row)

        clicked_next = _click_next_inverter_report_page_if_possible(page)

        if not clicked_next:
            break

        page.wait_for_timeout(1800)

    return all_rows

def _pick_cell(
    headers: list[str],
    cells: list[str],
    possible_names: list[str],
    fallback_index: int | None = None,
) -> str | None:
    normalised_headers = [_normalise_col_name(h) for h in headers]
    possible = {_normalise_col_name(name) for name in possible_names}

    for idx, header in enumerate(normalised_headers):
        if header in possible or any(p in header for p in possible):
            if idx < len(cells):
                return cells[idx].strip() or None

    if fallback_index is not None and fallback_index < len(cells):
        return cells[fallback_index].strip() or None

    return None


    input_selectors = [
        "input#deviceName",
        "xpath=//label[@for='deviceName']/ancestor::div[contains(@class, 'ant-form-item')]//input",
        "xpath=//label[normalize-space()='Device name']/ancestor::div[contains(@class, 'ant-form-item')]//input",
    ]

    found = False

    for selector in input_selectors:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            target = loc.first
            target.wait_for(state="visible", timeout=5000)
            target.scroll_into_view_if_needed(timeout=3000)
            target.click(timeout=3000)
            target.fill("")
            target.type(inverter_name, delay=20)
            found = True
            break

        except Exception:
            continue

    if not found:
        raise RuntimeError(
            "Could not find Device Management 'Device name' input. "
            "Expected input#deviceName."
        )
    
    page.wait_for_timeout(300)

    search_selectors = [
        "xpath=//input[@id='deviceName']/ancestor::div[contains(@class, 'ant-form') or contains(@class, 'ant-row')][1]/following::button[.//span[normalize-space()='Search']][1]",
        "xpath=//button[.//span[normalize-space()='Search']]",
        "button:has-text('Search')",
    ]

    clicked = False

    for selector in search_selectors:
        try:
            buttons = page.locator(selector)

            if buttons.count() == 0:
                continue

            for idx in range(buttons.count()):
                button = buttons.nth(idx)

                if not button.is_visible(timeout=800):
                    continue

                button.scroll_into_view_if_needed(timeout=3000)
                dismiss_cookie_policy(page)
                button.click(timeout=5000, no_wait_after=True)
                clicked = True
                break

        except Exception:
            continue

    if not clicked:
        try:
            page.locator("input#deviceName").press("Enter")
            clicked = True
        
        except Exception:
            pass

    if not clicked:
        raise RuntimeError(
            f"Could not click Device Management Search button for inverter '{inverter_name}'."
        )
    
    page.wait_for_timeout(2500)
    dismiss_cookie_policy(page)

def _looks_like_fusionsolar_ne_id(value: str | None) -> bool:
    text_value = str(value or "").strip().upper()
    return text_value.startswith("NE=")

def _clean_inverter_sn(value: str | None) -> str | None:
    text_value = str(value or "").strip()

    if not text_value:
        return None

    if _looks_like_fusionsolar_ne_id(text_value):
        return None

    bad_values = {
        "DEVICE TYPEALL",
        "DEVICE TYPE ALL",
        "ALL",
        "SN",
        "DEVICE NAME",
        "DEVICE TYPE",
        "PLANT NAME",
    }

    compact = " ".join(text_value.upper().split())

    if compact in bad_values:
        return None

    if "DEVICE TYPE" in compact:
        return None

    if "DEVICE NAME" in compact:
        return None

    if len(text_value) < 6:
        return None

    return text_value

def _open_device_management(page: Page) -> None:
    _click_first_visible(
        page,
        [
            "span.monitor-tab[title='Device Management'] a",
            "span.monitor-tab:has-text('Device Management') a",
            "a:has-text('Device Management')",
            "xpath=//a[normalize-space()='Device Management']",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(1500)
    dismiss_cookie_policy(page)

def _search_device_management_inverter(page: Page, inverter_name: str) -> None:
    input_selectors = [
        "input#deviceName",
        "xpath=//label[@for='deviceName']/ancestor::div[contains(@class, 'ant-form-item')]//input",
        "xpath=//label[normalize-space()='Device name']/ancestor::div[contains(@class, 'ant-form-item')]//input",
    ]

    found = False

    for selector in input_selectors:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            target = loc.first
            target.wait_for(state="visible", timeout=5000)
            target.scroll_into_view_if_needed(timeout=3000)
            target.click(timeout=3000)
            target.fill("")
            target.type(inverter_name, delay=20)

            found = True
            break

        except Exception:
            continue

    if not found:
        raise RuntimeError(
            "Could not find Device Management 'Device name' input. "
            "Expected input#deviceName."
        )

    page.wait_for_timeout(300)

    search_selectors = [
        "xpath=//input[@id='deviceName']/ancestor::div[contains(@class, 'ant-form') or contains(@class, 'ant-row')][1]/following::button[.//span[normalize-space()='Search']][1]",
        "xpath=//button[.//span[normalize-space()='Search']]",
        "button:has-text('Search')",
    ]

    clicked = False

    for selector in search_selectors:
        try:
            buttons = page.locator(selector)

            if buttons.count() == 0:
                continue

            for idx in range(buttons.count()):
                button = buttons.nth(idx)

                if not button.is_visible(timeout=800):
                    continue

                button.scroll_into_view_if_needed(timeout=3000)
                dismiss_cookie_policy(page)
                button.click(timeout=5000, no_wait_after=True)
                clicked = True
                break

            if clicked:
                break

        except Exception:
            continue

    if not clicked:
        try:
            page.locator("input#deviceName").press("Enter")
            clicked = True
        except Exception:
            pass

    if not clicked:
        raise RuntimeError(
            f"Could not click Device Management Search button for inverter '{inverter_name}'."
        )

    page.wait_for_timeout(2500)
    dismiss_cookie_policy(page)

def _extract_sn_from_device_management_table(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
) -> str | None:
    result = page.evaluate(
        r"""
        ({ plantName, inverterName }) => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const normKey = (text) => normalise(text)
                .replace(/[^A-Za-z0-9]+/g, " ")
                .replace(/\s+/g, " ")
                .trim()
                .toUpperCase();

            const wantedPlant = normKey(plantName);
            const wantedInverter = normKey(inverterName);

            const isBadSn = (value) => {
                const clean = normKey(value);

                if (!clean) return true;
                if (clean.startsWith("NE=")) return true;
                if (clean === "SN") return true;
                if (clean === "ALL") return true;
                if (clean === "DEVICE TYPEALL") return true;
                if (clean === "DEVICE TYPE ALL") return true;
                if (clean.includes("DEVICE TYPE")) return true;
                if (clean.includes("DEVICE NAME")) return true;
                if (clean.includes("PLANT NAME")) return true;
                if (clean.length < 6) return true;

                return false;
            };

            const cellText = (cell) => {
                if (!cell) return "";

                const titleNode = cell.querySelector("[title]");
                const value =
                    cell.getAttribute("title") ||
                    (titleNode ? titleNode.getAttribute("title") : "") ||
                    cell.textContent ||
                    "";

                return normalise(value);
            };

            const scoreMatch = (wanted, candidate) => {
                const w = normKey(wanted);
                const c = normKey(candidate);

                if (!w || !c) return 0;
                if (w === c) return 1000;
                if (c.includes(w) || w.includes(c)) return 850;

                const wantedTokens = w.split(" ").filter(Boolean);
                const candidateTokens = new Set(c.split(" ").filter(Boolean));

                if (!wantedTokens.length) return 0;

                const hits = wantedTokens.filter((token) => candidateTokens.has(token)).length;
                return (hits / wantedTokens.length) * 700;
            };

            const findHeaderIndexes = () => {
                const headers = Array.from(document.querySelectorAll("thead.ant-table-thead th"));

                const indexes = {
                    deviceName: -1,
                    plantName: -1,
                    sn: -1,
                };

                headers.forEach((th, index) => {
                    const text = normKey(th.getAttribute("title") || th.textContent || "");

                    if (text === "DEVICE NAME") indexes.deviceName = index;
                    if (text === "PLANT NAME") indexes.plantName = index;
                    if (text === "SN") indexes.sn = index;
                });

                return indexes;
            };

            const indexes = findHeaderIndexes();

            const rows = Array.from(document.querySelectorAll(
                "tbody.ant-table-tbody tr.ant-table-row, " +
                "tbody.ant-table-tbody tr"
            ));

            let best = null;

            for (const row of rows) {
                const rect = row.getBoundingClientRect();

                if (!rect.width || !rect.height) {
                    continue;
                }

                const cells = Array.from(row.querySelectorAll("td.ant-table-cell, td"));
                const rowText = normalise(row.textContent || "");

                if (!rowText) {
                    continue;
                }

                let deviceNameText = "";
                let plantNameText = "";
                let snText = "";

                if (indexes.deviceName >= 0 && cells[indexes.deviceName]) {
                    deviceNameText = cellText(cells[indexes.deviceName]);
                }

                if (indexes.plantName >= 0 && cells[indexes.plantName]) {
                    plantNameText = cellText(cells[indexes.plantName]);
                }

                if (indexes.sn >= 0 && cells[indexes.sn]) {
                    snText = cellText(cells[indexes.sn]);
                }

                if (!snText) {
                    const snCell = row.querySelector("td.device-sn-column, .device-sn-column");
                    snText = cellText(snCell);
                }

                if (!deviceNameText) {
                    const links = Array.from(row.querySelectorAll("a, span, div"));
                    const bestNameNode = links
                        .map((node) => cellText(node))
                        .filter(Boolean)
                        .sort((a, b) => scoreMatch(inverterName, b) - scoreMatch(inverterName, a))[0];

                    deviceNameText = bestNameNode || "";
                }

                const inverterScore = scoreMatch(inverterName, deviceNameText);
                const rowInverterScore = scoreMatch(inverterName, rowText);
                const plantScore = plantNameText
                    ? scoreMatch(plantName, plantNameText)
                    : scoreMatch(plantName, rowText);

                const finalInverterScore = Math.max(inverterScore, rowInverterScore);

                if (finalInverterScore < 700) {
                    continue;
                }

                if (wantedPlant && plantScore < 500) {
                    continue;
                }

                if (isBadSn(snText)) {
                    continue;
                }

                const totalScore = finalInverterScore + plantScore;

                if (!best || totalScore > best.score) {
                    best = {
                        score: totalScore,
                        sn: snText,
                        deviceNameText,
                        plantNameText,
                        rowText,
                    };
                }
            }

            if (!best) {
                return {
                    found: false,
                    sn: null,
                    rowCount: rows.length,
                    indexes,
                };
            }

            return {
                found: true,
                sn: best.sn,
                score: best.score,
                deviceNameText: best.deviceNameText,
                plantNameText: best.plantNameText,
                rowText: best.rowText,
                rowCount: rows.length,
                indexes,
            };
        }
        """,
        {
            "plantName": plant_name,
            "inverterName": inverter_name,
        },
    )

    if not result.get("found"):
        print(
            f"  Could not extract SN from Device Management table for "
            f"{plant_name} / {inverter_name}. "
            f"Rows: {result.get('rowCount')}, indexes: {result.get('indexes')}"
        )
        return None

    sn = _clean_inverter_sn(result.get("sn"))

    if not sn:
        print(
            f"  Ignored invalid SN from Device Management table for "
            f"{plant_name} / {inverter_name}: {result.get('sn')}"
        )
        return None

    print(
        f"  Real inverter SN from Device Management table: {sn} | "
        f"matched row device={result.get('deviceNameText')} | "
        f"score={float(result.get('score') or 0):.2f}"
    )

    return sn

def _mark_best_device_management_inverter_link(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
) -> dict:
    return page.evaluate(
        r"""
        ({ plantName, inverterName }) => {
            const normalise = (text) => (text || "")
                .replace(/\u00a0/g, " ")
                .replace(/[^A-Za-z0-9]+/g, " ")
                .replace(/\s+/g, " ")
                .trim()
                .toUpperCase();

            const tokenRatio = (wanted, candidate) => {
                const wantedTokens = normalise(wanted).split(" ").filter(Boolean);
                const candidateTokens = new Set(normalise(candidate).split(" ").filter(Boolean));

                if (!wantedTokens.length) {
                    return 0;
                }

                const hits = wantedTokens.filter((token) => candidateTokens.has(token)).length;
                return hits / wantedTokens.length;
            };

            const wantedPlant = normalise(plantName);
            const wantedInverter = normalise(inverterName);

            document.querySelectorAll("[data-spms-device-row-match='true']").forEach((node) => {
                node.removeAttribute("data-spms-device-row-match");
            });

            const rows = Array.from(document.querySelectorAll(
                "tbody.ant-table-tbody tr.ant-table-row, " +
                "tbody.ant-table-tbody tr, " +
                "tr.ant-table-row"
            ));

            let best = null;

            for (const row of rows) {
                const rowRect = row.getBoundingClientRect();

                if (!rowRect.width || !rowRect.height) {
                    continue;
                }

                const rowText = row.textContent || row.innerText || "";
                const normalisedRow = normalise(rowText);

                if (!normalisedRow) {
                    continue;
                }

                const plantExact = wantedPlant && normalisedRow.includes(wantedPlant);
                const plantRatio = wantedPlant ? tokenRatio(wantedPlant, normalisedRow) : 1;

                if (wantedPlant && !plantExact && plantRatio < 0.7) {
                    continue;
                }

                const clickableNodes = Array.from(row.querySelectorAll("a, td"));

                for (const node of clickableNodes) {
                    const rawText =
                        node.getAttribute("title") ||
                        node.textContent ||
                        node.innerText ||
                        "";

                    const candidate = normalise(rawText);

                    if (!candidate) {
                        continue;
                    }

                    let score = 0;

                    if (candidate === wantedInverter) {
                        score = 1000;
                    } else if (candidate.includes(wantedInverter) || wantedInverter.includes(candidate)) {
                        score = 850;
                    } else {
                        score = tokenRatio(wantedInverter, candidate) * 700;
                    }

                    if (plantExact) {
                        score += 250;
                    } else {
                        score += plantRatio * 150;
                    }

                    if (!best || score > best.score) {
                        best = {
                            node,
                            row,
                            score,
                            rawText,
                            rowText,
                        };
                    }
                }
            }

            if (!best || best.score < 360) {
                return {
                    matched: false,
                    bestText: best ? best.rawText : null,
                    bestRowText: best ? best.rowText : null,
                    bestScore: best ? best.score : 0,
                    rowCount: rows.length,
                };
            }

            best.node.setAttribute("data-spms-device-row-match", "true");

            return {
                matched: true,
                matchedText: best.rawText,
                matchedRowText: best.rowText,
                score: best.score,
                rowCount: rows.length,
            };
        }
        """,
        {
            "plantName": plant_name,
            "inverterName": inverter_name,
        },
    )

def _click_device_management_inverter(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
) -> None:
    _search_device_management_inverter(page, inverter_name)

    match = _mark_best_device_management_inverter_link(
        page,
        plant_name=plant_name,
        inverter_name=inverter_name,
    )

    if not match.get("matched"):
        raise RuntimeError(
            f"Could not find inverter '{inverter_name}' for plant '{plant_name}' "
            f"in Device Management. Best match: {match.get('bestText')}. "
            f"Best row: {match.get('bestRowText')}. "
            f"Best score: {match.get('bestScore')}."
        )

    print(
        f"  Matched inverter details row: {match.get('matchedText')} | "
        f"score={match.get('score'):.2f}"
    )

    target = page.locator("[data-spms-device-row-match='true']").first
    target.wait_for(state="visible", timeout=10000)
    target.scroll_into_view_if_needed(timeout=5000)

    dismiss_cookie_policy(page)
    target.click(timeout=15000, no_wait_after=True)

    page.wait_for_timeout(2500)
    dismiss_cookie_policy(page)

def _open_details_tab_if_possible(page: Page) -> None:
    selectors = [
        "a:has-text('Details')",
        "span.monitor-tab[title='Details'] a",
        "span.monitor-tab:has-text('Details') a",
        "xpath=//a[normalize-space()='Details']",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            for idx in range(loc.count()):
                item = loc.nth(idx)

                if not item.is_visible(timeout=800):
                    continue

                item.scroll_into_view_if_needed(timeout=3000)
                dismiss_cookie_policy(page)
                item.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(1200)
                return

        except Exception:
            continue

def _extract_inverter_sn_from_details(page: Page) -> str | None:
    sn = page.evaluate(
        r"""
        () => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const isSnLabel = (text) => {
                const clean = normalise(text).replace(/[:：]/g, "").toUpperCase();
                return clean === "SN";
            };

            const containers = Array.from(document.querySelectorAll(
                ".ant-col.ant-col-8, " +
                ".odd-line, " +
                ".even-line, " +
                ".ant-row, " +
                "div"
            ));

            for (const container of containers) {
                const children = Array.from(container.children || []);

                if (children.length < 2) {
                    continue;
                }

                const left = children[0];
                const right = children[1];

                const leftText = normalise(
                    left.getAttribute("title") ||
                    left.textContent ||
                    ""
                );

                if (!isSnLabel(leftText)) {
                    continue;
                }

                const rightCandidate =
                    right.querySelector("[title]") ||
                    right;

                const value = normalise(
                    rightCandidate.getAttribute("title") ||
                    rightCandidate.textContent ||
                    ""
                );

                if (value) {
                    return value;
                }
            }

            const labelNodes = Array.from(document.querySelectorAll("[title], span, div"))
                .filter((node) => isSnLabel(node.getAttribute("title") || node.textContent || ""));

            for (const labelNode of labelNodes) {
                let parent = labelNode.parentElement;

                for (let depth = 0; depth < 5 && parent; depth++) {
                    const valueNodes = Array.from(parent.querySelectorAll("[title], div, span"))
                        .filter((node) => node !== labelNode)
                        .map((node) => normalise(node.getAttribute("title") || node.textContent || ""))
                        .filter(Boolean)
                        .filter((value) => !isSnLabel(value));

                    for (const value of valueNodes) {
                        if (value && !value.toUpperCase().startsWith("NE=")) {
                            return value;
                        }
                    }

                    parent = parent.parentElement;
                }
            }

            return null;
        }
        """
    )

    return _clean_inverter_sn(sn)

def _resolve_real_sn_for_inverter(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
) -> str | None:
    _search_device_management_inverter(page, inverter_name)

    sn = _extract_sn_from_device_management_table(
        page,
        plant_name=plant_name,
        inverter_name=inverter_name,
    )

    if sn:
        return sn

    return None

def _return_to_device_management_after_details(
    page: Page,
    *,
    plant_name: str,
) -> None:
    try:
        page.go_back(wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2500)
        dismiss_cookie_policy(page)

        possible_device_management_tabs = [
            "span.monitor-tab[title='Device Management'] a",
            "span.monitor-tab:has-text('Device Management') a",
            "a:has-text('Device Management')",
            "xpath=//a[normalize-space()='Device Management']",
        ]

        for selector in possible_device_management_tabs:
            try:
                loc = page.locator(selector)

                if loc.count() > 0 and loc.first.is_visible(timeout=1000):
                    _open_device_management(page)
                    return

            except Exception:
                continue

    except Exception:
        pass

    try:
        _click_plant_in_tree(page, plant_name)
        _open_device_management(page)
        page.wait_for_timeout(1500)
        dismiss_cookie_policy(page)
        return

    except Exception as exc:
        raise RuntimeError(
            f"Could not return to Device Management page for plant '{plant_name}' "
            f"after reading inverter Details. Last error: {exc}"
        ) from exc

def _parse_inverter_report_payload(payload: list[dict], selected_plant: str) -> list[InverterReportRow]:
    rows: list[InverterReportRow] = []
    seen: set[tuple[str, str]] = set()

    for item in payload:
        headers = item.get("headers") or []
        cells = item.get("cells") or []

        if not cells:
            continue

        plant_name = _pick_cell(headers, cells, ["Plant Name"], 0) or selected_plant
        inverter_name = _pick_cell(headers, cells, ["Device Name", "Inverter Name"], 1)

        if not inverter_name:
            continue

        inverter_sn = _clean_inverter_sn(
            _pick_cell(headers, cells, ["SN", "Device SN", "Serial Number"])
        )

        total_capacity = _to_decimal(
            _pick_cell(
                headers,
                cells,
                ["Total String Capacity", "Total String Capacity (kWp)"],
                2,
            )
        )

        yield_kwh = _to_decimal(
            _pick_cell(
                headers,
                cells,
                ["Yield", "Yield (kWh)"],
                3,
            )
        )

        total_yield = _to_decimal(
            _pick_cell(
                headers,
                cells,
                ["Total Yield", "Total Yield (kWh)"],
                4,
            )
        )

        specific_energy = _to_decimal(
            _pick_cell(
                headers,
                cells,
                ["Specific Energy", "Specific Energy (kWh/kWp)"],
                5,
            )
        )

        key = (plant_name.upper(), inverter_name.upper())

        if key in seen:
            continue

        seen.add(key)

        rows.append(
            InverterReportRow(
                plant_name=plant_name,
                inverter_name=inverter_name,
                inverter_sn=inverter_sn,
                total_string_capacity_kwp=total_capacity,
                yield_kwh=yield_kwh,
                total_yield_kwh=total_yield,
                specific_energy_kwh_kwp=specific_energy,
            )
        )

    return rows

def fetch_inverter_report_for_plant(
    page: Page,
    *,
    plant_name: str,
    report_day: date | None = None,
) -> list[InverterReportRow]:
    _click_plant_in_tree(page, plant_name)
    _open_report_management(page)
    _open_inverter_report_tab(page)
    _set_report_date_if_possible(page, report_day)
    _click_search_if_possible(page)

    payload = _extract_inverter_report_rows_from_table(page)
    rows = _parse_inverter_report_payload(payload, selected_plant=plant_name)

    if not rows:
        raise RuntimeError(f"No inverter report rows were found for plant '{plant_name}'.")

    return rows

def detect_low_performing_inverters_for_plant(
    plant: LowPshPlant,
    inverter_rows: list[InverterReportRow],
    *,
    run_day: date | None = None,
    threshold_pct: Decimal = INVERTER_THRESHOLD_PCT,
) -> list[LowPerformingInverterResult]:
    run_day = run_day or today_gmt8()

    valid_rows = [
        r
        for r in inverter_rows
        if r.specific_energy_kwh_kwp is not None
    ]

    if len(valid_rows) < 2:
        return []

    benchmark = max(
        r.specific_energy_kwh_kwp
        for r in valid_rows
        if r.specific_energy_kwh_kwp is not None
    )

    if benchmark <= 0:
        return []

    threshold_factor = Decimal("1") - (Decimal(str(threshold_pct)) / Decimal("100"))
    threshold_psh = benchmark * threshold_factor

    results: list[LowPerformingInverterResult] = []

    for row in valid_rows:
        inverter_psh = row.specific_energy_kwh_kwp

        if inverter_psh is None:
            continue

        deviation_pct = ((benchmark - inverter_psh) / benchmark) * Decimal("100")
        is_low = inverter_psh < threshold_psh

        if not is_low:
            continue

        reason = (
            f"{row.inverter_name} PSH is {deviation_pct.quantize(Decimal('0.01'))}% lower "
            f"than the highest inverter PSH in {plant.plant_name}."
        )

        results.append(
            LowPerformingInverterResult(
                run_day=run_day,
                plant_name=plant.plant_name,
                city=plant.city,
                plant_status=plant.plant_status,
                plant_psh=plant.plant_psh,
                city_avg_psh=plant.city_avg_psh,
                inverter_name=row.inverter_name,
                inverter_sn=row.inverter_sn,
                inverter_psh=inverter_psh,
                benchmark_inverter_psh=benchmark,
                threshold_inverter_psh=threshold_psh,
                deviation_pct_vs_benchmark=deviation_pct.quantize(Decimal("0.01")),
                underperforming=True,
                reason=reason,
            )
        )

    return results

def resolve_real_inverter_sns_for_results(
    page: Page,
    *,
    plant_name: str,
    results: list[LowPerformingInverterResult],
) -> list[LowPerformingInverterResult]:
    if not results:
        return results

    try:
        _click_plant_in_tree(page, plant_name)
        _open_device_management(page)
    except Exception as exc:
        print(f"  Could not open Device Management for SN resolution: {exc}")
        return results

    for result in results:
        current_sn = _clean_inverter_sn(result.inverter_sn)

        if current_sn:
            result.inverter_sn = current_sn
            continue

        try:
            real_sn = _resolve_real_sn_for_inverter(
                page,
                plant_name=plant_name,
                inverter_name=result.inverter_name,
            )

            if real_sn:
                result.inverter_sn = real_sn

        except Exception as exc:
            print(
                f"  Failed to resolve real SN for "
                f"{plant_name} / {result.inverter_name}: {exc}"
            )

    return results

def result_to_dict(result: LowPerformingInverterResult) -> dict:
    return {
        "run_day": result.run_day,
        "plant_name": result.plant_name,
        "city": result.city,
        "plant_status": result.plant_status,
        "plant_psh": _decimal_to_float(result.plant_psh),
        "city_avg_psh": _decimal_to_float(result.city_avg_psh),
        "inverter_name": result.inverter_name,
        "inverter_sn": result.inverter_sn,
        "inverter_psh": _decimal_to_float(result.inverter_psh),
        "benchmark_inverter_psh": _decimal_to_float(result.benchmark_inverter_psh),
        "threshold_inverter_psh": _decimal_to_float(result.threshold_inverter_psh),
        "deviation_pct_vs_benchmark": _decimal_to_float(result.deviation_pct_vs_benchmark),
        "underperforming": result.underperforming,
        "reason": result.reason,
    }

def ensure_low_performing_inverters_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS low_performing_inverters_latest (
                run_day date NOT NULL,
                plant_name text NOT NULL,
                city text,
                plant_status text,
                plant_psh double precision,
                city_avg_psh double precision,
                inverter_name text NOT NULL,
                inverter_sn text,
                inverter_psh double precision NOT NULL,
                benchmark_inverter_psh double precision NOT NULL,
                threshold_inverter_psh double precision NOT NULL,
                deviation_pct_vs_benchmark double precision NOT NULL,
                underperforming boolean NOT NULL DEFAULT true,
                reason text,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (run_day, plant_name, inverter_name)
            )
            """
        )
    )

def persist_low_performing_inverters(
    db: Session,
    rows: list[dict],
    *,
    run_day: date | None = None,
) -> int:
    run_day = run_day or today_gmt8()

    ensure_low_performing_inverters_table(db)

    db.execute(
        text("DELETE FROM low_performing_inverters_latest WHERE run_day = :run_day"),
        {"run_day": run_day},
    )

    for row in rows:
        db.execute(
            text(
                """
                INSERT INTO low_performing_inverters_latest (
                    run_day,
                    plant_name,
                    city,
                    plant_status,
                    plant_psh,
                    city_avg_psh,
                    inverter_name,
                    inverter_sn,
                    inverter_psh,
                    benchmark_inverter_psh,
                    threshold_inverter_psh,
                    deviation_pct_vs_benchmark,
                    underperforming,
                    reason
                )
                VALUES (
                    :run_day,
                    :plant_name,
                    :city,
                    :plant_status,
                    :plant_psh,
                    :city_avg_psh,
                    :inverter_name,
                    :inverter_sn,
                    :inverter_psh,
                    :benchmark_inverter_psh,
                    :threshold_inverter_psh,
                    :deviation_pct_vs_benchmark,
                    :underperforming,
                    :reason
                )
                ON CONFLICT (run_day, plant_name, inverter_name)
                DO UPDATE SET
                    city = EXCLUDED.city,
                    plant_status = EXCLUDED.plant_status,
                    plant_psh = EXCLUDED.plant_psh,
                    city_avg_psh = EXCLUDED.city_avg_psh,
                    inverter_sn = EXCLUDED.inverter_sn,
                    inverter_psh = EXCLUDED.inverter_psh,
                    benchmark_inverter_psh = EXCLUDED.benchmark_inverter_psh,
                    threshold_inverter_psh = EXCLUDED.threshold_inverter_psh,
                    deviation_pct_vs_benchmark = EXCLUDED.deviation_pct_vs_benchmark,
                    underperforming = EXCLUDED.underperforming,
                    reason = EXCLUDED.reason,
                    created_at = now()
                """
            ),
            row,
        )

    db.commit()
    return len(rows)

def fetch_and_detect_low_performing_inverters_from_fusionsolar(
    plants: list[LowPshPlant],
    *,
    report_day: date | None = None,
    headless: bool = False,
    interactive_login: bool = False,
    threshold_pct: Decimal = INVERTER_THRESHOLD_PCT,
) -> list[dict]:
    report_day = report_day or today_gmt8()
    all_results: list[dict] = []

    if not plants:
        return all_results

    with sync_playwright() as p:
        browser, context = create_fusionsolar_context(p, headless=headless)
        page = context.new_page()

        try:
            open_fusionsolar_target(
                page,
                context,
                FUSIONSOLAR_STATION_LIST_URL,
                interactive_login=interactive_login,
            )

            page.wait_for_timeout(1500)
            dismiss_cookie_policy(page)

            for plant in plants:
                print(f"Checking low-performing inverters for plant: {plant.plant_name}")

                try:
                    inverter_rows = fetch_inverter_report_for_plant(
                        page,
                        plant_name=plant.plant_name,
                        report_day=report_day,
                    )

                    results = detect_low_performing_inverters_for_plant(
                        plant,
                        inverter_rows,
                        run_day=report_day,
                        threshold_pct=threshold_pct,
                    )

                    results = resolve_real_inverter_sns_for_results(
                        page,
                        plant_name=plant.plant_name,
                        results=results,
                    )

                    all_results.extend(result_to_dict(result) for result in results)

                    print(
                        f"  Inverters found: {len(inverter_rows)}\n"
                        f"  Low-performing inverters: {len(results)}\n"
                    )

                except Exception as exc:
                    print(f"  Failed to check plant '{plant.plant_name}': {exc}")

        finally:
            browser.close()

    return all_results