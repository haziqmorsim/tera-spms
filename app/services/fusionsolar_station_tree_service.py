from __future__ import annotations
import re
from typing import Iterable
from playwright.sync_api import Page
from app.services.playwright_client import dismiss_cookie_policy

def click_first_visible(
    page: Page,
    selectors: Iterable[str],
    *,
    timeout: int = 10000,
) -> None:
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

    raise RuntimeError(
        f"Could not click any selector: {list(selectors)}. Last error: {last_error}"
    )

def compact_name(value: str | None) -> str:
    text_value = str(value or "").replace("\u00a0", " ")
    text_value = text_value.replace("…", " ").replace("...", " ")
    text_value = re.sub(r"[^A-Za-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip().upper()

def search_terms_for_plant(plant_name: str) -> list[str]:
    raw = re.sub(r"\s+", " ", str(plant_name or "").strip())
    no_parentheses = re.sub(r"\([^)]*\)", " ", raw)
    no_punctuation = re.sub(r"[^A-Za-z0-9]+", " ", no_parentheses)
    tokens = [t for t in no_punctuation.split() if t]

    candidate_terms = [
        raw,
        no_parentheses.strip(),
        " ".join(tokens[:7]),
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

def station_tree_node_count(page: Page) -> int:
    try:
        return page.locator("span.node-name").count()
    except Exception:
        return 0

def clear_station_tree_search(page: Page) -> None:
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
            dismiss_cookie_policy(page)
            return

        except Exception:
            continue

def search_station_tree(page: Page, term: str) -> bool:
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

def click_more_until_loaded(page: Page, *, max_clicks: int = 100) -> int:
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

        before = station_tree_node_count(page)

        try:
            more_links.nth(visible_index).scroll_into_view_if_needed(timeout=3000)
            more_links.nth(visible_index).click(timeout=5000, no_wait_after=True)

            clicks += 1
            page.wait_for_timeout(1200)

            after = station_tree_node_count(page)

            if after <= before:
                page.wait_for_timeout(1200)

                if station_tree_node_count(page) <= before:
                    break

        except Exception:
            break

    return clicks

def mark_best_station_node_match(page: Page, plant_name: str) -> dict:
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

def click_marked_station_node(page: Page) -> None:
    target = page.locator("span.node-name[data-spms-plant-match='true']").first
    target.wait_for(state="visible", timeout=10000)
    target.scroll_into_view_if_needed(timeout=5000)

    dismiss_cookie_policy(page)
    target.click(timeout=10000, no_wait_after=True)

    page.wait_for_timeout(1800)
    dismiss_cookie_policy(page)

def click_plant_in_station_tree(page: Page, plant_name: str) -> None:
    dismiss_cookie_policy(page)
    page.wait_for_selector("span.node-name, input[placeholder*='device' i]", timeout=30000)

    attempts: list[str] = []
    last_match: dict | None = None

    match = mark_best_station_node_match(page, plant_name)
    last_match = match

    if match.get("matched"):
        print(f"  Matched plant: {match.get('matchedText')} | score={match.get('score'):.2f}")
        click_marked_station_node(page)
        return

    for term in search_terms_for_plant(plant_name):
        attempts.append(f"search:{term}")

        if search_station_tree(page, term):
            click_more_until_loaded(page, max_clicks=20)

            match = mark_best_station_node_match(page, plant_name)
            last_match = match

            if match.get("matched"):
                print(
                    f"  Matched plant: {match.get('matchedText')} | "
                    f"score={match.get('score'):.2f} | search='{term}'"
                )
                click_marked_station_node(page)
                return

    attempts.append("clear-search")
    clear_station_tree_search(page)
    page.wait_for_timeout(800)

    more_clicks = click_more_until_loaded(page, max_clicks=100)
    attempts.append(f"clicked-more:{more_clicks}")

    match = mark_best_station_node_match(page, plant_name)
    last_match = match

    if match.get("matched"):
        print(
            f"  Matched plant: {match.get('matchedText')} | "
            f"score={match.get('score'):.2f} | after More"
        )
        click_marked_station_node(page)
        return

    raise RuntimeError(
        f"Could not find plant '{plant_name}' in the station tree. "
        f"Attempts: {attempts}. "
        f"Loaded nodes: {last_match.get('nodeCount') if last_match else 'unknown'}. "
        f"Best visible match: {last_match.get('bestText') if last_match else None}. "
        f"Best score: {last_match.get('bestScore') if last_match else None}."
    )