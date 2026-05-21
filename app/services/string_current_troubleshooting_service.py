from __future__ import annotations
import os
import re
from pathlib import Path
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.fusionsolar_station_tree_service import (
    click_first_visible,
    click_plant_in_station_tree,
)
from app.services.playwright_client import (
    create_fusionsolar_context,
    dismiss_cookie_policy,
    open_fusionsolar_target,
)
from app.utils.time_utils import today_gmt8

load_dotenv()

FUSIONSOLAR_STATION_LIST_URL = os.getenv(
    "FUSIONSOLAR_STATION_LIST_URL",
    "https://intl.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-7-5c65c6ee-49c2-4032-ae36-222b03f97b37#/view/station",
)

LOW_STRING_CURRENT_THRESHOLD_PCT = Decimal(os.getenv("LOW_STRING_CURRENT_THRESHOLD_PCT", "20"))

STRING_CURRENT_START_TIME = os.getenv("STRING_CURRENT_START_TIME", "07:30")
STRING_CURRENT_END_TIME = os.getenv("STRING_CURRENT_END_TIME", "19:30")
STRING_CURRENT_INTERVAL_MINUTES = int(os.getenv("STRING_CURRENT_INTERVAL_MINUTES", "5"))

@dataclass(slots=True)
class LowPerformingInverter:
    run_day: date
    plant_name: str
    city: str | None
    plant_status: str | None
    inverter_name: str
    inverter_sn: str | None
    inverter_psh: Decimal | None
    benchmark_inverter_psh: Decimal | None
    deviation_pct_vs_benchmark: Decimal | None

@dataclass(slots=True)
class StringCurrentReading:
    timestamp: datetime
    string_name: str
    current_amp: Decimal

@dataclass(slots=True)
class LowPerformingStringResult:
    run_day: date
    plant_name: str
    city: str | None
    plant_status: str | None
    inverter_name: str
    inverter_sn: str | None
    string_name: str
    string_total_current: Decimal
    benchmark_string_current: Decimal
    threshold_string_current: Decimal
    deviation_pct_vs_benchmark: Decimal
    underperforming: bool
    reason: str

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

def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()

def _parse_chart_timestamp(value) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value)
        except Exception:
            return None

    text_value = str(value).strip()

    if not text_value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(text_value, fmt)

            if fmt in {"%H:%M:%S", "%H:%M"}:
                return datetime.combine(today_gmt8(), parsed.time())

            return parsed

        except ValueError:
            continue

    return None

def _normalise_string_name(value: str) -> str:
    text_value = str(value or "").replace("\u00a0", " ")
    text_value = re.sub(r"\s+", " ", text_value).strip()

    match = re.fullmatch(
        r"PV\s*(\d+)\s+input\s+current\s*\(\s*A\s*\)",
        text_value,
        re.I,
    )

    if match:
        return f"PV{int(match.group(1))} input current(A)"

    return text_value

def _build_allowed_string_signal_set(signal_names: list[str]) -> set[str]:
    allowed: set[str] = set()

    for signal_name in signal_names:
        normalised = _normalise_string_name(signal_name)

        if re.fullmatch(
            r"PV\d+\s+input\s+current\s*\(\s*A\s*\)",
            normalised,
            re.I,
        ):
            allowed.add(normalised.upper())

    return allowed

def _generate_5_minute_timestamps(report_day: date) -> list[datetime]:
    start_time = _parse_hhmm(STRING_CURRENT_START_TIME)
    end_time = _parse_hhmm(STRING_CURRENT_END_TIME)

    current = datetime.combine(report_day, start_time)
    end = datetime.combine(report_day, end_time)

    timestamps: list[datetime] = []

    while current <= end:
        timestamps.append(current)
        current += timedelta(minutes=STRING_CURRENT_INTERVAL_MINUTES)

    return timestamps

def fetch_latest_low_performing_inverters(db: Session) -> list[LowPerformingInverter]:
    rows = (
        db.execute(
            text(
                """
                SELECT
                    run_day,
                    plant_name,
                    city,
                    plant_status,
                    inverter_name,
                    inverter_sn,
                    inverter_psh,
                    benchmark_inverter_psh,
                    deviation_pct_vs_benchmark
                FROM low_performing_inverters_latest
                WHERE run_day = (
                    SELECT MAX(run_day)
                    FROM low_performing_inverters_latest
                )
                  AND underperforming = true
                ORDER BY plant_name ASC, inverter_name ASC
                """
            )
        )
        .mappings()
        .all()
    )

    return [
        LowPerformingInverter(
            run_day=r["run_day"],
            plant_name=r["plant_name"],
            city=r.get("city"),
            plant_status=r.get("plant_status"),
            inverter_name=r["inverter_name"],
            inverter_sn=r.get("inverter_sn"),
            inverter_psh=_to_decimal(r.get("inverter_psh")),
            benchmark_inverter_psh=_to_decimal(r.get("benchmark_inverter_psh")),
            deviation_pct_vs_benchmark=_to_decimal(r.get("deviation_pct_vs_benchmark")),
        )
        for r in rows
    ]

def _open_device_management(page: Page) -> None:
    click_first_visible(
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

def _mark_best_inverter_link(
    page: Page,
    inverter_name: str,
    inverter_sn: str | None = None,
    plant_name: str | None = None,
) -> dict:
    return page.evaluate(
        r"""
        ({ inverterName, inverterSn, plantName }) => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/[^A-Za-z0-9]+/g, " ")
                .replace(/\s+/g, " ")
                .trim()
                .toUpperCase();

            const rawClean = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const tokenRatio = (wanted, candidate) => {
                const wantedTokens = normalise(wanted).split(" ").filter(Boolean);
                const candidateTokens = new Set(normalise(candidate).split(" ").filter(Boolean));

                if (!wantedTokens.length) {
                    return 0;
                }

                const hits = wantedTokens.filter((token) => candidateTokens.has(token)).length;
                return hits / wantedTokens.length;
            };

            const wantedName = normalise(inverterName);
            const wantedSn = normalise(inverterSn || "");
            const wantedPlant = normalise(plantName || "");

            document.querySelectorAll("[data-spms-inverter-match='true']").forEach((node) => {
                node.removeAttribute("data-spms-inverter-match");
            });

            const headerCells = Array.from(document.querySelectorAll("thead.ant-table-thead th"));
            let deviceNameIndex = -1;
            let plantNameIndex = -1;
            let snIndex = -1;

            headerCells.forEach((th, index) => {
                const title = normalise(th.getAttribute("title") || th.textContent || "");

                if (title === "DEVICE NAME") {
                    deviceNameIndex = index;
                }

                if (title === "PLANT NAME") {
                    plantNameIndex = index;
                }

                if (title === "SN") {
                    snIndex = index;
                }
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

                const cells = Array.from(row.querySelectorAll("td.ant-table-cell, td"));
                const rowText = rawClean(row.textContent || row.innerText || "");
                const rowCandidate = normalise(rowText);

                if (!rowCandidate) {
                    continue;
                }

                let plantText = "";
                let snText = "";
                let deviceNameText = "";

                if (plantNameIndex >= 0 && cells[plantNameIndex]) {
                    plantText = rawClean(
                        cells[plantNameIndex].getAttribute("title") ||
                        cells[plantNameIndex].textContent ||
                        ""
                    );
                }

                if (snIndex >= 0 && cells[snIndex]) {
                    snText = rawClean(
                        cells[snIndex].getAttribute("title") ||
                        cells[snIndex].textContent ||
                        ""
                    );
                }

                let deviceCell = null;

                if (deviceNameIndex >= 0 && cells[deviceNameIndex]) {
                    deviceCell = cells[deviceNameIndex];
                    deviceNameText = rawClean(
                        deviceCell.getAttribute("title") ||
                        deviceCell.textContent ||
                        ""
                    );
                }

                if (wantedPlant) {
                    const plantExact = normalise(plantText).includes(wantedPlant) || rowCandidate.includes(wantedPlant);
                    const plantRatio = Math.max(
                        tokenRatio(wantedPlant, plantText),
                        tokenRatio(wantedPlant, rowText)
                    );

                    if (!plantExact && plantRatio < 0.7) {
                        continue;
                    }
                }

                let clickableNode = null;

                if (deviceCell) {
                    clickableNode =
                        deviceCell.querySelector("a[href], a, span[role='link'], .ant-typography a") ||
                        deviceCell.querySelector("span, div") ||
                        deviceCell;
                }

                if (!clickableNode) {
                    const linkCandidates = Array.from(row.querySelectorAll("a[href], a"));

                    clickableNode = linkCandidates.find((node) => {
                        const text = normalise(
                            node.getAttribute("title") ||
                            node.textContent ||
                            node.innerText ||
                            ""
                        );

                        return text === wantedName || text.includes(wantedName) || wantedName.includes(text);
                    }) || null;
                }

                if (!clickableNode) {
                    continue;
                }

                const clickableText = rawClean(
                    clickableNode.getAttribute("title") ||
                    clickableNode.textContent ||
                    clickableNode.innerText ||
                    deviceNameText ||
                    ""
                );

                const candidatesToScore = [
                    clickableText,
                    deviceNameText,
                    rowText,
                ];

                let nameScore = 0;

                for (const candidateText of candidatesToScore) {
                    const candidate = normalise(candidateText);

                    if (!candidate) {
                        continue;
                    }

                    let score = 0;

                    if (candidate === wantedName) {
                        score = 1000;
                    } else if (candidate.includes(wantedName) || wantedName.includes(candidate)) {
                        score = 850;
                    } else {
                        score = tokenRatio(wantedName, candidateText) * 700;
                    }

                    if (score > nameScore) {
                        nameScore = score;
                    }
                }

                if (nameScore < 350) {
                    continue;
                }

                let totalScore = nameScore;

                if (wantedSn) {
                    const rowSn = normalise(snText || rowText);

                    if (rowSn.includes(wantedSn)) {
                        totalScore += 250;
                    }
                }

                if (wantedPlant) {
                    const rowPlant = normalise(plantText || rowText);

                    if (rowPlant.includes(wantedPlant)) {
                        totalScore += 250;
                    } else {
                        totalScore += tokenRatio(wantedPlant, plantText || rowText) * 150;
                    }
                }

                const nodeRect = clickableNode.getBoundingClientRect();

                if (!nodeRect.width || !nodeRect.height) {
                    totalScore -= 150;
                }

                if (!best || totalScore > best.score) {
                    best = {
                        node: clickableNode,
                        row,
                        score: totalScore,
                        rawText: clickableText || deviceNameText,
                        rowText,
                        plantText,
                        snText,
                        deviceNameIndex,
                        plantNameIndex,
                        snIndex,
                    };
                }
            }

            if (!best || best.score < 360) {
                return {
                    matched: false,
                    bestText: best ? best.rawText : null,
                    bestRowText: best ? best.rowText : null,
                    bestScore: best ? best.score : 0,
                    rowCount: rows.length,
                    deviceNameIndex,
                    plantNameIndex,
                    snIndex,
                };
            }

            best.node.setAttribute("data-spms-inverter-match", "true");

            return {
                matched: true,
                matchedText: best.rawText,
                matchedRowText: best.rowText,
                matchedPlantText: best.plantText,
                matchedSnText: best.snText,
                score: best.score,
                rowCount: rows.length,
                deviceNameIndex,
                plantNameIndex,
                snIndex,
            };
        }
        """,
        {
            "inverterName": inverter_name,
            "inverterSn": inverter_sn or "",
            "plantName": plant_name or "",
        },
    )

def _historical_information_tab_exists(page: Page) -> bool:
    selectors = [
        "a:has-text('Historical Information')",
        "span.monitor-tab[title='Historical Information'] a",
        "span.monitor-tab:has-text('Historical Information') a",
        "xpath=//a[normalize-space()='Historical Information']",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)

            if loc.count() > 0 and loc.first.is_visible(timeout=1000):
                return True

        except Exception:
            continue

    return False

def _search_device_management_inverter(page: Page, inverter_name: str) -> None:
    device_name_input_selectors = [
        "input#deviceName",
        "xpath=//label[@for='deviceName']/ancestor::div[contains(@class, 'ant-form-item')]//input",
        "xpath=//label[normalize-space()='Device name']/ancestor::div[contains(@class, 'ant-form-item')]//input",
    ]

    input_found = False

    for selector in device_name_input_selectors:
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

            input_found = True
            break

        except Exception:
            continue

    if not input_found:
        raise RuntimeError(
            "Could not find the Device Management 'Device name' input field. "
            "Expected selector: input#deviceName"
        )

    page.wait_for_timeout(300)

    search_button_selectors = [
        "xpath=//input[@id='deviceName']/ancestor::div[contains(@class, 'ant-row')][1]/following::button[.//span[normalize-space()='Search']][1]",
        "xpath=//label[@for='deviceName']/ancestor::div[contains(@class, 'ant-form') or contains(@class, 'ant-row')][1]/following::button[.//span[normalize-space()='Search']][1]",
        "xpath=//button[.//span[normalize-space()='Search']]",
        "button:has-text('Search')",
    ]

    clicked_search = False

    for selector in search_button_selectors:
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
                clicked_search = True
                break

            if clicked_search:
                break

        except Exception:
            continue

    if not clicked_search:
        try:
            page.locator("input#deviceName").press("Enter")
            clicked_search = True
        except Exception:
            pass

    if not clicked_search:
        raise RuntimeError(
            f"Could not click the Device Management Search button after entering inverter '{inverter_name}'."
        )

    page.wait_for_timeout(2500)
    dismiss_cookie_policy(page)

def _click_low_performing_inverter(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
    inverter_sn: str | None,
) -> None:
    _search_device_management_inverter(page, inverter_name)

    match = _mark_best_inverter_link(
        page,
        inverter_name,
        inverter_sn,
        plant_name,
    )

    if not match.get("matched"):
        raise RuntimeError(
            f"Could not find clickable inverter '{inverter_name}' for plant '{plant_name}' "
            f"in Device Management. "
            f"Best visible match: {match.get('bestText')}. "
            f"Best row: {match.get('bestRowText')}. "
            f"Best score: {match.get('bestScore')}. "
            f"Row count: {match.get('rowCount')}. "
            f"Column indexes: device={match.get('deviceNameIndex')}, "
            f"plant={match.get('plantNameIndex')}, sn={match.get('snIndex')}."
        )

    print(
        f"  Matched inverter: {match.get('matchedText')} | "
        f"score={float(match.get('score') or 0):.2f}"
    )

    target = page.locator("[data-spms-inverter-match='true']").first
    target.wait_for(state="visible", timeout=10000)
    target.scroll_into_view_if_needed(timeout=5000)

    dismiss_cookie_policy(page)

    target.click(timeout=15000, no_wait_after=True)
    page.wait_for_timeout(3500)
    dismiss_cookie_policy(page)

    if _historical_information_tab_exists(page):
        return

    try:
        target.dblclick(timeout=8000, no_wait_after=True)
        page.wait_for_timeout(3500)
        dismiss_cookie_policy(page)

        if _historical_information_tab_exists(page):
            return

    except Exception:
        pass

    try:
        target.focus(timeout=5000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3500)
        dismiss_cookie_policy(page)

        if _historical_information_tab_exists(page):
            return

    except Exception:
        pass

    raise RuntimeError(
        f"Matched inverter '{inverter_name}' for plant '{plant_name}', "
        "but clicking the Device Name did not open the inverter page. "
        "Historical Information tab was not found after click."
    )

def _open_historical_information(page: Page) -> None:
    click_first_visible(
        page,
        [
            "a:has-text('Historical Information')",
            "span.monitor-tab[title='Historical Information'] a",
            "span.monitor-tab:has-text('Historical Information') a",
            "xpath=//a[normalize-space()='Historical Information']",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(2500)
    dismiss_cookie_policy(page)

def _set_historical_date_if_possible(page: Page, report_day: date) -> None:
    date_text = report_day.strftime("%Y-%m-%d")

    candidates = [
        "input[placeholder='Select date']",
        ".dpdesign-picker-input input",
        ".ant-picker input",
        "input[readonly][title]",
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
            return

        except Exception:
            continue

def _open_signal_point_dropdown(page: Page) -> None:
    click_first_visible(
        page,
        [
            ".ant-select-selection-overflow",
            ".ant-select-selector:has(input[role='combobox'])",
            "input[role='combobox']",
            "div:has(> input#rc_select_2)",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(1000)

def _select_all_input_current_signals(page: Page) -> list[str]:
    _open_signal_point_dropdown(page)

    selected = page.evaluate(
        r"""
        async () => {
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

            const normalise = (text) => (text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const isInputCurrent = (text) => {
                const clean = normalise(text).toLowerCase();
                return clean.includes("input current(a)");
            };

            const shouldForceUncheck = (text) => {
                const clean = normalise(text).toLowerCase();
                return (
                    clean.includes("active power(kw)") ||
                    clean.includes("total input power(kw)")
                );
            };

            const isChecked = (checkbox) => {
                if (!checkbox) return false;

                const classText = checkbox.className || "";
                const ariaChecked = checkbox.getAttribute("aria-checked");

                return (
                    classText.includes("checked") ||
                    ariaChecked === "true"
                );
            };

            const clickCheckbox = (checkbox) => {
                if (!checkbox) return false;

                const inner =
                    checkbox.querySelector(".ant-select-tree-checkbox-inner") ||
                    checkbox.querySelector(".ant-tree-checkbox-inner") ||
                    checkbox;

                inner.click();
                return true;
            };

            const getNodeText = (node) => {
                return normalise(
                    node.querySelector(".ant-select-tree-title")?.textContent ||
                    node.querySelector(".ant-tree-title")?.textContent ||
                    node.querySelector("[title]")?.getAttribute("title") ||
                    node.getAttribute("title") ||
                    node.textContent ||
                    ""
                );
            };

            const processVisibleNodes = () => {
                const selectedNames = [];

                const nodes = Array.from(document.querySelectorAll(
                    ".ant-select-tree-treenode, " +
                    ".ant-tree-treenode, " +
                    ".ant-select-tree-list-holder-inner .ant-select-tree-treenode, " +
                    ".rc-virtual-list-holder-inner .ant-select-tree-treenode"
                ));

                for (const node of nodes) {
                    const text = getNodeText(node);

                    if (!text) {
                        continue;
                    }

                    const checkbox =
                        node.querySelector(".ant-select-tree-checkbox") ||
                        node.querySelector(".ant-tree-checkbox");

                    if (!checkbox) {
                        continue;
                    }

                    const checked = isChecked(checkbox);

                    if (shouldForceUncheck(text) && checked) {
                        clickCheckbox(checkbox);
                        continue;
                    }

                    if (isInputCurrent(text)) {
                        if (!checked) {
                            clickCheckbox(checkbox);
                        }

                        selectedNames.push(text);
                    }
                }

                return selectedNames;
            };

            const dropdown =
                document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)") ||
                document.querySelector(".ant-select-tree") ||
                document.body;

            const scrollCandidates = Array.from(document.querySelectorAll(
                ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .rc-virtual-list-holder, " +
                ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-list-holder, " +
                ".ant-select-tree-list-holder, " +
                ".rc-virtual-list-holder"
            ));

            const scrollContainer =
                scrollCandidates.find((el) => el.scrollHeight > el.clientHeight) ||
                dropdown;

            const found = new Set();

            for (let pass = 0; pass < 70; pass++) {
                const names = processVisibleNodes();

                for (const name of names) {
                    if (isInputCurrent(name)) {
                        found.add(name);
                    }
                }

                if (!scrollContainer || !scrollContainer.scrollTo) {
                    break;
                }

                const before = scrollContainer.scrollTop;

                scrollContainer.scrollTo({
                    top: scrollContainer.scrollTop + Math.max(160, scrollContainer.clientHeight - 40),
                    behavior: "auto",
                });

                await sleep(180);

                const after = scrollContainer.scrollTop;

                if (after === before) {
                    break;
                }
            }

            if (scrollContainer && scrollContainer.scrollTo) {
                scrollContainer.scrollTo({ top: 0, behavior: "auto" });
                await sleep(120);
            }

            processVisibleNodes();

            return Array.from(found);
        }
        """
    )

    page.wait_for_timeout(1000)

    if not selected:
        raise RuntimeError(
            "No signal points containing 'input current(A)' were found."
        )

    print(f"  Selected input current signals: {', '.join(selected)}")
    return selected

def _click_historical_search(page: Page) -> None:
    click_first_visible(
        page,
        [
            "button[type='submit'].ant-btn-primary:has-text('Search')",
            "button.ant-btn-primary:has-text('Search')",
            "button.dpdesign-btn-primary:has-text('Search')",
            "xpath=//button[.//span[normalize-space()='Search'] or normalize-space()='Search']",
        ],
        timeout=15000,
    )

    page.wait_for_timeout(7000)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

def _get_chart_mouse_point_for_timestamp(page: Page, target_timestamp: datetime) -> dict | None:
    timestamp_text = target_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_text_no_seconds = target_timestamp.strftime("%Y-%m-%d %H:%M")
    short_time = target_timestamp.strftime("%H:%M")
    short_time_with_seconds = target_timestamp.strftime("%H:%M:%S")

    return page.evaluate(
        r"""
        ({ timestampText, timestampTextNoSeconds, shortTime, shortTimeWithSeconds }) => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const chartNodes = Array.from(document.querySelectorAll(
                ".historical-chart-wrapper .echarts-for-react, " +
                ".echarts-for-react, " +
                "div[_echarts_instance_]"
            ));

            const getGridRect = (chart) => {
                try {
                    const grid = chart.getModel().getComponent("grid", 0);
                    const rect = grid.coordinateSystem.getRect();

                    return {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                    };
                } catch (err) {
                    return null;
                }
            };

            const getXAxisData = (chart) => {
                try {
                    const option = chart.getOption ? chart.getOption() : null;

                    if (
                        option &&
                        option.xAxis &&
                        option.xAxis[0] &&
                        Array.isArray(option.xAxis[0].data)
                    ) {
                        return option.xAxis[0].data;
                    }
                } catch (err) {}

                return [];
            };

            const findDataIndex = (xAxisData) => {
                const wantedLabels = [
                    timestampText,
                    timestampTextNoSeconds,
                    shortTimeWithSeconds,
                    shortTime,
                ];

                for (let i = 0; i < xAxisData.length; i++) {
                    const label = normalise(xAxisData[i]);

                    for (const wanted of wantedLabels) {
                        if (
                            label === wanted ||
                            label.includes(wanted) ||
                            wanted.includes(label)
                        ) {
                            return i;
                        }
                    }
                }

                const parts = shortTime.split(":");
                const hour = Number(parts[0]);
                const minute = Number(parts[1]);

                if (Number.isFinite(hour) && Number.isFinite(minute)) {
                    return Math.round(((hour * 60) + minute) / 5);
                }

                return -1;
            };

            for (const node of chartNodes) {
                const rect = node.getBoundingClientRect();

                if (!rect.width || !rect.height) {
                    continue;
                }

                const instanceId = node.getAttribute("_echarts_instance_");

                if (!instanceId || !window.echarts) {
                    continue;
                }

                const chart = window.echarts.getInstanceByDom(node);

                if (!chart) {
                    continue;
                }

                const gridRect = getGridRect(chart) || {
                    x: rect.width * 0.07,
                    y: rect.height * 0.12,
                    width: rect.width * 0.86,
                    height: rect.height * 0.70,
                };

                const xAxisData = getXAxisData(chart);
                const dataIndex = findDataIndex(xAxisData);

                if (dataIndex < 0) {
                    continue;
                }

                let localX = null;

                try {
                    const xValue = xAxisData[dataIndex] ?? dataIndex;
                    const pixel = chart.convertToPixel({ xAxisIndex: 0 }, xValue);

                    if (Array.isArray(pixel)) {
                        localX = Number(pixel[0]);
                    } else {
                        localX = Number(pixel);
                    }
                } catch (err) {
                    localX = null;
                }

                if (!Number.isFinite(localX)) {
                    const pointCount =
                        xAxisData && xAxisData.length > 1
                            ? xAxisData.length
                            : 288;

                    const boundedIndex = Math.max(0, Math.min(dataIndex, pointCount - 1));
                    localX = gridRect.x + (boundedIndex / Math.max(1, pointCount - 1)) * gridRect.width;
                }

                const localY = gridRect.y + gridRect.height * 0.45;

                return {
                    ok: true,
                    pageX: rect.left + localX,
                    pageY: rect.top + localY,
                    localX,
                    localY,
                    dataIndex,
                    xAxisLength: xAxisData.length,
                    timestampText,
                };
            }

            return null;
        }
        """,
        {
            "timestampText": timestamp_text,
            "timestampTextNoSeconds": timestamp_text_no_seconds,
            "shortTime": short_time,
            "shortTimeWithSeconds": short_time_with_seconds,
        },
    )

def _trigger_chart_tooltip_at_point(page: Page, point: dict) -> None:
    page_x = float(point["pageX"])
    page_y = float(point["pageY"])

    page.mouse.move(page_x, page_y)
    page.wait_for_timeout(120)

    page.evaluate(
        r"""
        ({ pageX, pageY }) => {
            const target =
                document.elementFromPoint(pageX, pageY) ||
                document.querySelector(".historical-chart-wrapper canvas") ||
                document.querySelector(".echarts-for-react canvas") ||
                document.querySelector("canvas");

            if (!target) {
                return;
            }

            const eventOptions = {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: pageX,
                clientY: pageY,
                screenX: pageX,
                screenY: pageY,
            };

            target.dispatchEvent(new MouseEvent("mousemove", eventOptions));
            target.dispatchEvent(new MouseEvent("mouseover", eventOptions));
        }
        """,
        {
            "pageX": page_x,
            "pageY": page_y,
        },
    )

    page.wait_for_timeout(160)

def _try_echarts_show_tip(page: Page, target_timestamp: datetime) -> None:
    timestamp_text = target_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_text_no_seconds = target_timestamp.strftime("%Y-%m-%d %H:%M")
    short_time = target_timestamp.strftime("%H:%M")
    short_time_with_seconds = target_timestamp.strftime("%H:%M:%S")

    page.evaluate(
        r"""
        ({ timestampText, timestampTextNoSeconds, shortTime, shortTimeWithSeconds }) => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const chartNodes = Array.from(document.querySelectorAll(
                ".historical-chart-wrapper .echarts-for-react, " +
                ".echarts-for-react, " +
                "div[_echarts_instance_]"
            ));

            const isInputCurrentSeries = (name) => {
                return normalise(name).toLowerCase().includes("input current(a)");
            };

            for (const node of chartNodes) {
                const instanceId = node.getAttribute("_echarts_instance_");

                if (!instanceId || !window.echarts) {
                    continue;
                }

                const chart = window.echarts.getInstanceByDom(node);

                if (!chart) {
                    continue;
                }

                const option = chart.getOption ? chart.getOption() : null;

                if (!option || !option.series || !option.series.length) {
                    continue;
                }

                let seriesIndex = 0;

                for (let i = 0; i < option.series.length; i++) {
                    if (isInputCurrentSeries(option.series[i].name)) {
                        seriesIndex = i;
                        break;
                    }
                }

                const xAxisData =
                    option.xAxis &&
                    option.xAxis[0] &&
                    Array.isArray(option.xAxis[0].data)
                        ? option.xAxis[0].data
                        : [];

                let dataIndex = -1;
                const wantedLabels = [
                    timestampText,
                    timestampTextNoSeconds,
                    shortTimeWithSeconds,
                    shortTime,
                ];

                for (let i = 0; i < xAxisData.length; i++) {
                    const label = normalise(xAxisData[i]);

                    for (const wanted of wantedLabels) {
                        if (
                            label === wanted ||
                            label.includes(wanted) ||
                            wanted.includes(label)
                        ) {
                            dataIndex = i;
                            break;
                        }
                    }

                    if (dataIndex >= 0) {
                        break;
                    }
                }

                if (dataIndex < 0) {
                    const parts = shortTime.split(":");
                    const hour = Number(parts[0]);
                    const minute = Number(parts[1]);

                    if (Number.isFinite(hour) && Number.isFinite(minute)) {
                        dataIndex = Math.round(((hour * 60) + minute) / 5);
                    }
                }

                if (dataIndex < 0) {
                    continue;
                }

                try {
                    chart.dispatchAction({
                        type: "showTip",
                        seriesIndex,
                        dataIndex,
                    });
                } catch (err) {}
            }
        }
        """,
        {
            "timestampText": timestamp_text,
            "timestampTextNoSeconds": timestamp_text_no_seconds,
            "shortTime": short_time,
            "shortTimeWithSeconds": short_time_with_seconds,
        },
    )

    page.wait_for_timeout(120)

def _extract_tooltip_values_from_dom(page: Page) -> dict:
    return page.evaluate(
        r"""
        () => {
            const normalise = (text) => String(text || "")
                .replace(/\u00a0/g, " ")
                .replace(/\s+/g, " ")
                .trim();

            const canonicalSignalName = (text) => {
                const clean = normalise(text);
                const match = clean.match(/^PV\s*(\d+)\s+input\s+current\s*\(\s*A\s*\)$/i);

                if (!match) {
                    return null;
                }

                return `PV${Number(match[1])} input current(A)`;
            };

            const isInputCurrent = (text) => {
                return canonicalSignalName(text) !== null;
            };

            const extractTimestamp = (text) => {
                const match = String(text || "").match(/\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?/);
                return match ? match[0] : null;
            };

            const candidates = [];

            const tooltipContainers = Array.from(document.querySelectorAll(".tooltip-container"));

            for (const container of tooltipContainers) {
                let root = container;

                for (let i = 0; i < 10; i++) {
                    if (!root.parentElement) {
                        break;
                    }

                    root = root.parentElement;

                    if (extractTimestamp(root.textContent || "")) {
                        break;
                    }
                }

                const rawText = root.textContent || container.textContent || "";

                if (!normalise(rawText).toLowerCase().includes("input current(a)")) {
                    continue;
                }

                candidates.push({
                    root,
                    container,
                    rawText,
                    timestamp: extractTimestamp(rawText),
                    score: rawText.length + 10000,
                });
            }

            if (!candidates.length) {
                const fallbackNodes = Array.from(document.querySelectorAll("div"))
                    .filter((node) => normalise(node.textContent || "").toLowerCase().includes("input current(a)"))
                    .map((node) => {
                        const rawText = node.textContent || "";

                        return {
                            root: node,
                            container: node,
                            rawText,
                            timestamp: extractTimestamp(rawText),
                            score: rawText.length,
                        };
                    })
                    .sort((a, b) => b.score - a.score)
                    .slice(0, 10);

                candidates.push(...fallbackNodes);
            }

            if (!candidates.length) {
                return {
                    timestamp: null,
                    values: {},
                    rawText: "",
                    foundTooltip: false,
                };
            }

            candidates.sort((a, b) => b.score - a.score);

            const selected = candidates[0];
            const container = selected.container;
            const rawText = selected.rawText;
            const timestamp = selected.timestamp;
            const values = {};

            const tooltipItems = Array.from(container.querySelectorAll(".tooltip-item"));

            for (const item of tooltipItems) {
                const valueNode = item.querySelector(".tooltip-value");

                if (!valueNode) {
                    continue;
                }

                const value = normalise(valueNode.textContent);
                let name = normalise(item.textContent);

                if (!name || value === "") {
                    continue;
                }

                name = normalise(name.replace(value, ""));
                name = canonicalSignalName(name);

                if (!name) {
                    continue;
                }

                values[name] = value;
            }

            if (!Object.keys(values).length) {
                const regex = /(PV\s*\d+\s+input\s+current\s*\(\s*A\s*\))\s*(-?\d+(?:\.\d+)?)/gi;
                let match;

                while ((match = regex.exec(rawText)) !== null) {
                    const name = canonicalSignalName(match[1]);

                    if (!name) {
                        continue;
                    }

                    values[name] = match[2];
                }
            }

            return {
                timestamp,
                values,
                rawText,
                foundTooltip: true,
            };
        }
        """
    )

def _get_chart_scan_area(page: Page) -> dict:
    return page.evaluate(
        r"""
        () => {
            const chartNode =
                document.querySelector(".historical-chart-wrapper .echarts-for-react") ||
                document.querySelector(".echarts-for-react") ||
                document.querySelector("div[_echarts_instance_]");

            if (!chartNode) {
                return {
                    ok: false,
                    reason: "No chart node found",
                };
            }

            chartNode.scrollIntoView({
                block: "center",
                inline: "center",
            });

            const rect = chartNode.getBoundingClientRect();

            if (!rect.width || !rect.height) {
                return {
                    ok: false,
                    reason: "Chart node has no visible size",
                };
            }

            let grid = null;

            try {
                const instanceId = chartNode.getAttribute("_echarts_instance_");

                if (instanceId && window.echarts) {
                    const chart = window.echarts.getInstanceByDom(chartNode);

                    if (chart) {
                        const gridModel = chart.getModel().getComponent("grid", 0);
                        const gridRect = gridModel.coordinateSystem.getRect();

                        grid = {
                            x: gridRect.x,
                            y: gridRect.y,
                            width: gridRect.width,
                            height: gridRect.height,
                        };
                    }
                }
            } catch (err) {
                grid = null;
            }

            if (!grid) {
                grid = {
                    x: rect.width * 0.08,
                    y: rect.height * 0.15,
                    width: rect.width * 0.84,
                    height: rect.height * 0.65,
                };
            }

            return {
                ok: true,
                left: rect.left + grid.x,
                right: rect.left + grid.x + grid.width,
                top: rect.top + grid.y,
                bottom: rect.top + grid.y + grid.height,
                y: rect.top + grid.y + grid.height * 0.45,
                width: grid.width,
                height: grid.height,
            };
        }
        """
    )

def _trigger_mousemove_on_chart(page: Page, x: float, y: float) -> None:
    page.mouse.move(x, y)
    page.wait_for_timeout(80)

    page.evaluate(
        r"""
        ({ x, y }) => {
            const target =
                document.elementFromPoint(x, y) ||
                document.querySelector(".historical-chart-wrapper canvas") ||
                document.querySelector(".echarts-for-react canvas") ||
                document.querySelector("canvas");

            if (!target) {
                return;
            }

            const options = {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: x,
                clientY: y,
                screenX: x,
                screenY: y,
            };

            target.dispatchEvent(new MouseEvent("mousemove", options));
            target.dispatchEvent(new MouseEvent("mouseover", options));
            target.dispatchEvent(new PointerEvent("pointermove", options));
        }
        """,
        {"x": x, "y": y},
    )

    page.wait_for_timeout(120)

def _extract_input_current_readings_by_tooltip(
    page: Page,
    *,
    report_day: date,
    allowed_signal_names: list[str] | None = None,
) -> list[StringCurrentReading]:
    page.wait_for_selector(".historical-chart-wrapper, .echarts-for-react, canvas", timeout=30000)
    page.wait_for_timeout(2000)

    try:
        page.locator(".historical-chart-wrapper, .echarts-for-react").first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
    except Exception:
        pass

    allowed_signals = _build_allowed_string_signal_set(allowed_signal_names or [])

    if not allowed_signals:
        raise RuntimeError(
            "No valid selected PV input current(A) signals were available for tooltip filtering."
        )

    scan_area = _get_chart_scan_area(page)

    if not scan_area.get("ok"):
        raise RuntimeError(f"Could not locate chart scan area: {scan_area.get('reason')}")

    start_time = _parse_hhmm(STRING_CURRENT_START_TIME)
    end_time = _parse_hhmm(STRING_CURRENT_END_TIME)

    readings: list[StringCurrentReading] = []
    seen: set[tuple[datetime, str]] = set()

    expected_points = len(_generate_5_minute_timestamps(report_day))

    left = float(scan_area["left"])
    right = float(scan_area["right"])
    y = float(scan_area["y"])
    width = max(1.0, right - left)

    step_px = max(2.0, min(6.0, width / 300.0))

    successful_tooltips = 0
    skipped_invalid_signals: set[str] = set()
    x = left

    while x <= right:
        _trigger_mousemove_on_chart(page, x, y)

        tooltip = _extract_tooltip_values_from_dom(page)
        values = tooltip.get("values") or {}

        if not values:
            x += step_px
            continue

        tooltip_timestamp = _parse_chart_timestamp(tooltip.get("timestamp"))

        if tooltip_timestamp is None:
            x += step_px
            continue

        if tooltip_timestamp.date() != report_day:
            x += step_px
            continue

        if not (start_time <= tooltip_timestamp.time() <= end_time):
            x += step_px
            continue

        added_for_this_tooltip = 0

        for string_name, current_value in values.items():
            normalised_string_name = _normalise_string_name(string_name)

            if normalised_string_name.upper() not in allowed_signals:
                skipped_invalid_signals.add(string_name)
                continue

            current_amp = _to_decimal(current_value)

            if current_amp is None:
                continue

            key = (tooltip_timestamp, normalised_string_name)

            if key in seen:
                continue

            seen.add(key)

            readings.append(
                StringCurrentReading(
                    timestamp=tooltip_timestamp,
                    string_name=normalised_string_name,
                    current_amp=current_amp,
                )
            )

            added_for_this_tooltip += 1

        if added_for_this_tooltip > 0:
            successful_tooltips += 1

        captured_timestamps = {reading.timestamp for reading in readings}

        if len(captured_timestamps) >= expected_points:
            break

        x += step_px

    if skipped_invalid_signals:
        print(
            "  Ignored invalid/non-selected tooltip signal names: "
            + ", ".join(sorted(skipped_invalid_signals)[:10])
        )

    if not readings:
        raise RuntimeError(
            "No input current(A) values were extracted from the chart tooltip. "
            "The script scanned across the chart but no readable selected PV string tooltips were found."
        )

    captured_timestamps = sorted({reading.timestamp for reading in readings})
    captured_strings = sorted({reading.string_name for reading in readings})

    print(
        f"  Tooltip timestamps extracted: {successful_tooltips} | "
        f"Tooltip readings extracted: {len(readings)} | "
        f"PV strings extracted: {len(captured_strings)}"
    )

    if captured_timestamps:
        print(
            f"  Tooltip time range: "
            f"{captured_timestamps[0].strftime('%H:%M')} - "
            f"{captured_timestamps[-1].strftime('%H:%M')}"
        )

    return readings

def fetch_string_current_readings_for_inverter(
    page: Page,
    *,
    plant_name: str,
    inverter_name: str,
    inverter_sn: str | None,
    report_day: date,
) -> list[StringCurrentReading]:
    click_plant_in_station_tree(page, plant_name)

    _open_device_management(page)

    _click_low_performing_inverter(
        page, 
        plant_name=plant_name, 
        inverter_name=inverter_name,
        inverter_sn=inverter_sn,
    )

    _open_historical_information(page)

    _set_historical_date_if_possible(page, report_day)

    selected_signals = _select_all_input_current_signals(page)
    print(f"  Selected string current signals: {len(selected_signals)}")

    _click_historical_search(page)

    readings = _extract_input_current_readings_by_tooltip(
        page,
        report_day=report_day,
        allowed_signal_names=selected_signals,
    )

    if not readings:
        raise RuntimeError(
            f"No string current readings were extracted for {plant_name} / {inverter_name}."
        )

    return readings

def detect_low_performing_strings_for_inverter(
    inverter: LowPerformingInverter,
    readings: list[StringCurrentReading],
    *,
    report_day: date,
    threshold_pct: Decimal = LOW_STRING_CURRENT_THRESHOLD_PCT,
) -> list[LowPerformingStringResult]:
    start_time = _parse_hhmm(STRING_CURRENT_START_TIME)
    end_time = _parse_hhmm(STRING_CURRENT_END_TIME)

    totals: dict[str, Decimal] = {}

    for reading in readings:
        reading_time = reading.timestamp.time()

        if not (start_time <= reading_time <= end_time):
            continue

        totals[reading.string_name] = (
            totals.get(reading.string_name, Decimal("0")) + reading.current_amp
        )

    if len(totals) < 2:
        return []
    
    included_totals = {
        string_name: total_current
        for string_name, total_current in totals.items()
        if not (Decimal("-5") <= total_current <= Decimal("1")) # excluded from calculation
    }

    if len(included_totals) < 2:
        return []

    benchmark = max(included_totals.values())

    if benchmark <= 0:
        return []

    threshold_factor = Decimal("1") - (Decimal(str(threshold_pct)) / Decimal("100"))
    threshold_current = benchmark * threshold_factor

    results: list[LowPerformingStringResult] = []

    for string_name, total_current in included_totals.items():
        deviation_pct = ((benchmark - total_current) / benchmark) * Decimal("100")
        is_low = total_current <= threshold_current

        if not is_low:
            continue

        reason = (
            f"{string_name} total current is "
            f"{deviation_pct.quantize(Decimal('0.01'))}% lower than the highest string current "
            f"for {inverter.inverter_name}."
        )

        results.append(
            LowPerformingStringResult(
                run_day=report_day,
                plant_name=inverter.plant_name,
                city=inverter.city,
                plant_status=inverter.plant_status,
                inverter_name=inverter.inverter_name,
                inverter_sn=inverter.inverter_sn,
                string_name=string_name,
                string_total_current=total_current,
                benchmark_string_current=benchmark,
                threshold_string_current=threshold_current,
                deviation_pct_vs_benchmark=deviation_pct.quantize(Decimal("0.01")),
                underperforming=True,
                reason=reason,
            )
        )

    return results

def result_to_dict(result: LowPerformingStringResult) -> dict:
    return {
        "run_day": result.run_day,
        "plant_name": result.plant_name,
        "city": result.city,
        "plant_status": result.plant_status,
        "inverter_name": result.inverter_name,
        "inverter_sn": result.inverter_sn,
        "string_name": result.string_name,
        "string_total_current": _decimal_to_float(result.string_total_current),
        "benchmark_string_current": _decimal_to_float(result.benchmark_string_current),
        "threshold_string_current": _decimal_to_float(result.threshold_string_current),
        "deviation_pct_vs_benchmark": _decimal_to_float(result.deviation_pct_vs_benchmark),
        "underperforming": result.underperforming,
        "reason": result.reason,
    }

def ensure_low_performing_strings_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS low_performing_strings_latest (
                run_day date NOT NULL,
                plant_name text NOT NULL,
                city text,
                plant_status text,
                inverter_name text NOT NULL,
                inverter_sn text,
                string_name text NOT NULL,
                string_total_current double precision NOT NULL,
                benchmark_string_current double precision NOT NULL,
                threshold_string_current double precision NOT NULL,
                deviation_pct_vs_benchmark double precision NOT NULL,
                underperforming boolean NOT NULL DEFAULT true,
                reason text,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (run_day, plant_name, inverter_name, string_name)
            )
            """
        )
    )

def persist_low_performing_strings(
    db: Session,
    rows: list[dict],
    *,
    run_day: date | None = None,
) -> int:
    run_day = run_day or today_gmt8()

    ensure_low_performing_strings_table(db)

    db.execute(
        text("DELETE FROM low_performing_strings_latest WHERE run_day = :run_day"),
        {"run_day": run_day},
    )

    for row in rows:
        db.execute(
            text(
                """
                INSERT INTO low_performing_strings_latest (
                    run_day,
                    plant_name,
                    city,
                    plant_status,
                    inverter_name,
                    inverter_sn,
                    string_name,
                    string_total_current,
                    benchmark_string_current,
                    threshold_string_current,
                    deviation_pct_vs_benchmark,
                    underperforming,
                    reason
                )
                VALUES (
                    :run_day,
                    :plant_name,
                    :city,
                    :plant_status,
                    :inverter_name,
                    :inverter_sn,
                    :string_name,
                    :string_total_current,
                    :benchmark_string_current,
                    :threshold_string_current,
                    :deviation_pct_vs_benchmark,
                    :underperforming,
                    :reason
                )
                ON CONFLICT (run_day, plant_name, inverter_name, string_name)
                DO UPDATE SET
                    city = EXCLUDED.city,
                    plant_status = EXCLUDED.plant_status,
                    inverter_sn = EXCLUDED.inverter_sn,
                    string_total_current = EXCLUDED.string_total_current,
                    benchmark_string_current = EXCLUDED.benchmark_string_current,
                    threshold_string_current = EXCLUDED.threshold_string_current,
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

def fetch_and_detect_low_performing_strings_from_fusionsolar(
    inverters: list[LowPerformingInverter],
    *,
    report_day: date | None = None,
    headless: bool = False,
    interactive_login: bool = False,
    threshold_pct: Decimal = LOW_STRING_CURRENT_THRESHOLD_PCT,
) -> list[dict]:
    report_day = report_day or today_gmt8()
    all_results: list[dict] = []

    if not inverters:
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

            for inverter in inverters:
                print(
                    f"Checking string current for "
                    f"{inverter.plant_name} / {inverter.inverter_name}"
                )

                try:
                    readings = fetch_string_current_readings_for_inverter(
                        page,
                        plant_name=inverter.plant_name,
                        inverter_name=inverter.inverter_name,
                        inverter_sn=inverter.inverter_sn,
                        report_day=report_day,
                    )

                    results = detect_low_performing_strings_for_inverter(
                        inverter,
                        readings,
                        report_day=report_day,
                        threshold_pct=threshold_pct,
                    )

                    all_results.extend(result_to_dict(result) for result in results)

                    unique_strings = sorted({r.string_name for r in readings})

                    print(
                        f"  Tooltip readings found: {len(readings)} | "
                        f"Strings found: {len(unique_strings)} | "
                        f"Low-performing strings: {len(results)}"
                    )

                except Exception as exc:
                    print(
                        f"  Failed to check strings for "
                        f"{inverter.plant_name} / {inverter.inverter_name}: {exc}"
                    )

        finally:
            browser.close()

    return all_results