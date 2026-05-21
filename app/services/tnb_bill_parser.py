from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import fitz
import pdfplumber
import pytesseract
from PIL import Image


MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "mac": 3, "apr": 4, "may": 5, "mei": 5, "jun": 6, "jul": 7, 
    "aug": 8, "ogo": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dis": 12,
}

MONTH_LABEL_EN = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

@dataclass
class MonthlyHistoryRow:
    month: int
    year: int
    month_label: str
    total_tnb_monthly_bill_rm: float | None = None
    total_usage_kwh: float | None = None

@dataclass
class ParsedTnbBill:
    company_name: str | None = None
    account_no: str | None = None
    invoice_no: str | None = None
    bill_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    no_of_days: int | None = None
    tariff_desc: str | None = None
    address: str | None = None
    state: str | None = None

    security_deposit_rm: float | None = None
    payment_period_start: date | None = None
    payment_period_end: date | None = None
    payment_amount_rm: float | None = None

    total_bill_rm: float | None = None
    utility_rm: float | None = None
    current_month_charge_rm: float | None = None
    kwtbb_rm: float | None = None

    peak_usage_kwh: float | None = None
    offpeak_usage_kwh: float | None = None
    total_usage_kwh: float | None = None
    max_demand_kw: float | None = None

    afa_rm: float | None = None
    peak_tariff_rm: float | None = None
    offpeak_tariff_rm: float | None = None
    capacity_charge_rm: float | None = None
    network_charge_rm: float | None = None
    retail_charge_rm: float | None = None

    history: list[MonthlyHistoryRow] = field(default_factory=list)
    raw_pages: list[str] = field(default_factory=list)

def _configure_tesseract() -> None:
    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()

def _clean_lines(text: str) -> list[str]:
    return [_normalize_line(x) for x in text.splitlines() if _normalize_line(x)]

def _parse_rm(text: str | None) -> float | None:
    if not text:
        return None

    cleaned = (
        str(text)
        .replace("RM", "")
        .replace("rm", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("−", "-")
        .replace("–", "-")
        .strip()
    )

    try:
        return float(cleaned)
    except ValueError:
        return None

def _parse_num(text: str | None) -> float | None:
    if not text:
        return None

    cleaned = (
        str(text)
        .replace(",", "")
        .replace(" ", "")
        .replace("−", "-")
        .replace("–", "-")
        .strip()
    )

    try:
        return float(cleaned)
    except ValueError:
        return None

def _parse_date_any(text: str | None) -> date | None:
    if not text:
        return None

    text = text.strip()

    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    return None

def _extract_text_pages(pdf_path: Path) -> list[str]:
    pages: list[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append((page.extract_text() or "").strip())

    if sum(len(p) for p in pages) >= 300:
        return pages

    _configure_tesseract()

    ocr_pages: list[str] = []
    doc = fitz.open(str(pdf_path))

    try:
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang="eng")
            ocr_pages.append(text.strip())
    finally:
        doc.close()

    return ocr_pages

def _extract_region_lines(
    page: pdfplumber.page.Page,
    x0: float,
    top: float,
    x1: float,
    bottom: float,
) -> list[str]:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)

    filtered = [
        w
        for w in words
        if w["x0"] >= x0
        and w["x1"] <= x1
        and w["top"] >= top
        and w["bottom"] <= bottom
    ]

    if not filtered:
        return []

    grouped: list[dict] = []

    for word in sorted(filtered, key=lambda w: (round(w["top"], 1), w["x0"])):
        matched = False

        for line in grouped:
            if abs(line["top"] - word["top"]) <= 2:
                line["words"].append(word)
                line["top"] = (line["top"] + word["top"]) / 2
                matched = True
                break

        if not matched:
            grouped.append({"top": word["top"], "words": [word]})

    result: list[str] = []

    for line in grouped:
        text = " ".join(w["text"] for w in sorted(line["words"], key=lambda w: w["x0"]))
        norm = _normalize_line(text)
        if norm:
            result.append(norm)

    return result

def _first_line_matching(lines: list[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.I)

    for line in lines:
        if regex.search(line):
            return line

    return None

def _find_line_index(lines: list[str], pattern: str) -> int | None:
    regex = re.compile(pattern, re.I)

    for idx, line in enumerate(lines):
        if regex.search(line):
            return idx

    return None

def _next_matching_line(
    lines: list[str],
    label_pattern: str,
    value_pattern: str,
    *,
    max_lookahead: int = 8,
) -> str | None:
    label_idx = _find_line_index(lines, label_pattern)
    if label_idx is None:
        return None

    value_regex = re.compile(value_pattern, re.I)

    for idx in range(label_idx + 1, min(len(lines), label_idx + 1 + max_lookahead)):
        line = lines[idx]
        if value_regex.search(line):
            return line

    return None

def _extract_first_date_range(text: str) -> tuple[date | None, date | None]:
    match = re.search(
        r"(\d{2}[./-]\d{2}[./-]\d{4})\s*-\s*(\d{2}[./-]\d{2}[./-]\d{4})",
        text,
    )

    if not match:
        return None, None

    return _parse_date_any(match.group(1)), _parse_date_any(match.group(2))

def _extract_days(text: str) -> int | None:
    match = re.search(r"\((\d+)\s*Hari\)", text, re.I)
    if match:
        return int(match.group(1))
    return None

def _parse_date_range_and_days_from_text(text: str) -> tuple[date | None, date | None, int | None]:
    start_date, end_date = _extract_first_date_range(text)
    no_of_days = _extract_days(text)
    return start_date, end_date, no_of_days

def _parse_last_amount_from_line(line: str | None) -> float | None:
    if not line:
        return None

    values = re.findall(r"([\d,]+\.\d{2})", line)
    return _parse_num(values[-1]) if values else None

def _parse_first_rm_from_text(text: str | None) -> float | None:
    if not text:
        return None

    match = re.search(r"RM\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
    if not match:
        return None

    return _parse_rm(match.group(1))

def _parse_first_amount_from_text(text: str | None) -> float | None:
    if not text:
        return None

    match = re.search(r"([\d,]+(?:\.\d{1,2})?)", text)
    if not match:
        return None

    return _parse_num(match.group(1))

def _find_line_startswith(lines: list[str], prefix: str) -> str | None:
    prefix_lower = prefix.lower()

    for line in lines:
        if line.lower().startswith(prefix_lower):
            return line

    return None

def _find_line_contains(lines: list[str], term: str) -> str | None:
    term_lower = term.lower()

    for line in lines:
        if term_lower in line.lower():
            return line

    return None

def _extract_company_address_from_page1(page1_obj, page1_lines: list[str]) -> tuple[str | None, str | None, str | None]:
    company_name = None
    address = None
    state = None

    if page1_obj is not None:
        address_block = _extract_region_lines(page1_obj, 20, 70, 230, 165)

        if address_block:
            company_name = address_block[0]
            state = address_block[-1] if len(address_block) >= 2 else None
            address = ", ".join(address_block[1:]) if len(address_block) >= 2 else None

    if company_name and address:
        return company_name, address, state

    label_idx = _find_line_index(page1_lines, r"ALAMAT\s+POS")
    stop_patterns = re.compile(
        r"TARIKH\s+BIL|TEMPOH\s+BIL|NO\.\s*INVOIS|NO\.\s*AKAUN|TARIF|DEPOSIT|BAYARAN|JUMLAH\s+BIL",
        re.I,
    )

    if label_idx is not None:
        block: list[str] = []

        for line in page1_lines[label_idx + 1 : label_idx + 12]:
            if stop_patterns.search(line):
                break
            block.append(line)

        cleaned = [x for x in block if not re.search(r"^\d{2}[./-]\d{2}[./-]\d{4}$", x)]

        if cleaned:
            company_name = company_name or cleaned[0]
            state = state or cleaned[-1]
            address = address or ", ".join(cleaned[1:])

    return company_name, address, state

def _extract_charge_rows(page2_lines: list[str], page2_text: str) -> dict[str, float | None]:
    def parse_charge_line(prefix: str, contains_term: str | None = None) -> float | None:
        line = _find_line_startswith(page2_lines, prefix)

        if line is None and contains_term:
            line = _find_line_contains(page2_lines, contains_term)

        if line:
            values = re.findall(r"([\d,]+\.\d{2})", line)
            if values:
                return _parse_num(values[-1])

        regex_term = contains_term or prefix
        match = re.search(
            rf"{re.escape(regex_term)}.*?([\d,]+\.\d{{2}})\s*$",
            page2_text,
            re.I | re.M,
        )

        if match:
            return _parse_num(match.group(1))

        return None

    return {
        "peak_usage_kwh": _parse_last_amount_from_line(_find_line_startswith(page2_lines, "Penggunaan Puncak")),
        "offpeak_usage_kwh": _parse_last_amount_from_line(_find_line_startswith(page2_lines, "Penggunaan Luar Puncak")),
        "total_usage_kwh": _parse_last_amount_from_line(_find_line_startswith(page2_lines, "Jumlah Penggunaan Anda")),
        "max_demand_kw": _parse_last_amount_from_line(_find_line_startswith(page2_lines, "Permintaan Maksima")),
        "peak_tariff_rm": parse_charge_line("Tenaga (Puncak)"),
        "offpeak_tariff_rm": parse_charge_line("Tenaga (Luar Puncak)"),
        "afa_rm": parse_charge_line("AFA", "AFA"),
        "capacity_charge_rm": parse_charge_line("Kapasiti"),
        "network_charge_rm": parse_charge_line("Caj Rangkaian"),
        "retail_charge_rm": parse_charge_line("Caj Peruncitan"),
        "current_month_charge_rm": parse_charge_line("Caj Penggunaan Bulan Semasa"),
        "kwtbb_rm": parse_charge_line("KWTBB"),
    }

def _extract_monthly_charge_history(page1_text: str) -> list[tuple[int, int, str, float | None]]:
    charge_match = re.search(
        r"Caj Bulanan \(RM\)(.*?)(?:Penggunaan \(kWh\)|Purata Caj Bulanan|Aras 3, Tower D)",
        page1_text,
        re.I | re.S,
    )

    if not charge_match:
        return []

    charge_section = charge_match.group(1)

    month_pairs = re.findall(
        r"\b(Feb|Mac|Mar|Apr|Mei|May|Jun|Jul|Ogo|Aug|Sep|Okt|Oct|Nov|Dis|Dec)-(\d{2})\b",
        charge_section,
        re.I,
    )

    charge_values = re.findall(r"RM\s*([\d,]+\.\d{2})", charge_section, re.I)

    rows: list[tuple[int, int, str, float | None]] = []

    for idx, (mon, yy) in enumerate(month_pairs):
        month_no = MONTH_MAP[mon.lower()]
        year = 2000 + int(yy)
        label = f"{MONTH_LABEL_EN[month_no]}-{yy}"
        amount = _parse_num(charge_values[idx]) if idx < len(charge_values) else None
        rows.append((year, month_no, label, amount))

    return rows

def _extract_six_month_history(page1_text: str) -> list[MonthlyHistoryRow]:
    charge_rows = _extract_monthly_charge_history(page1_text)

    rows: list[MonthlyHistoryRow] = []

    for year, month_no, label, amount in charge_rows:
        rows.append(
            MonthlyHistoryRow(
                month=month_no,
                year=year,
                month_label=label,
                total_tnb_monthly_bill_rm=amount,
                total_usage_kwh=None,
            )
        )

    rows.sort(key=lambda x: (x.year, x.month))
    return rows

def _extract_security_deposit(
    page1_obj,
    page1_lines: list[str],
    all_lines: list[str],
    page1_text: str,
    all_text: str,
) -> float | None:
    if page1_obj is not None:
        deposit_lines = _extract_region_lines(page1_obj, 220, 170, 390, 205)
        deposit_line = _first_line_matching(deposit_lines, r"RM|[\d,]+\.\d{1,2}|^0$")
        if deposit_line:
            parsed = _parse_first_rm_from_text(deposit_line)
            if parsed is not None:
                return parsed

            parsed = _parse_first_amount_from_text(deposit_line)
            if parsed is not None:
                return parsed

    deposit_line = _next_matching_line(
        all_lines,
        r"DEPOSIT\s+SEKURITI",
        r"RM\s*[\d,]+(?:\.\d{1,2})?|^[\d,]+(?:\.\d{1,2})?$|^0$",
        max_lookahead=6,
    )

    if deposit_line:
        parsed = _parse_first_rm_from_text(deposit_line)
        if parsed is not None:
            return parsed

        parsed = _parse_first_amount_from_text(deposit_line)
        if parsed is not None:
            return parsed

    match = re.search(
        r"DEPOSIT\s+SEKURITI\s*(?:RM)?\s*([\d,]+(?:\.\d{1,2})?|0)",
        all_text,
        re.I,
    )

    if match:
        return _parse_num(match.group(1))

    return None

def _extract_payment_for_period_and_amount(
    page1_obj,
    page1_lines: list[str],
    all_lines: list[str],
    page1_text: str,
    all_text: str,
    billing_start: date | None,
    billing_end: date | None,
) -> tuple[date | None, date | None, float | None]:
    payment_period_start = None
    payment_period_end = None
    payment_amount_rm = None

    if page1_obj is not None:
        payment_period_lines = _extract_region_lines(page1_obj, 380, 160, 610, 188)
        payment_period_text = " ".join(payment_period_lines)
        payment_period_start, payment_period_end = _extract_first_date_range(payment_period_text)

        payment_amount_lines = _extract_region_lines(page1_obj, 380, 180, 610, 205)
        payment_amount_text = " ".join(payment_amount_lines)
        payment_amount_rm = _parse_first_rm_from_text(payment_amount_text)

    label_idx = _find_line_index(all_lines, r"BAYARAN\s+BAGI\s+TEMPOH")

    if label_idx is not None:
        search_block = "\n".join(all_lines[label_idx + 1 : label_idx + 10])

        if payment_period_start is None or payment_period_end is None:
            payment_period_start, payment_period_end = _extract_first_date_range(search_block)

        if payment_amount_rm is None:
            payment_amount_rm = _parse_first_rm_from_text(search_block)

    if payment_period_start is None or payment_period_end is None or payment_amount_rm is None:
        match = re.search(
            r"BAYARAN\s+BAGI\s+TEMPOH\s*"
            r"(?P<period>.*?)(?P<amount>RM\s*[\d,]+(?:\.\d{1,2})?)",
            all_text,
            re.I | re.S,
        )

        if match:
            if payment_period_start is None or payment_period_end is None:
                payment_period_start, payment_period_end = _extract_first_date_range(match.group("period"))

            if payment_amount_rm is None:
                payment_amount_rm = _parse_first_rm_from_text(match.group("amount"))

    if payment_amount_rm is None:
        amaun_match = re.search(r"Amaun\s*:\s*RM\s*([\d,]+(?:\.\d{1,2})?)", all_text, re.I)
        if amaun_match:
            payment_amount_rm = _parse_rm(amaun_match.group(1))

    if payment_period_start is None or payment_period_end is None:
        tempoh_match = re.search(
            r"Tempoh\s+Bil\s*:\s*(\d{2}[./-]\d{2}[./-]\d{4})\s*-\s*(\d{2}[./-]\d{2}[./-]\d{4})",
            all_text,
            re.I,
        )

        if tempoh_match:
            payment_period_start = _parse_date_any(tempoh_match.group(1))
            payment_period_end = _parse_date_any(tempoh_match.group(2))

    if payment_period_start is None and billing_start is not None:
        payment_period_start = billing_start

    if payment_period_end is None and billing_end is not None:
        payment_period_end = billing_end

    return payment_period_start, payment_period_end, payment_amount_rm

def parse_tnb_bill_pdf(pdf_path: str | Path) -> ParsedTnbBill:
    pdf_path = Path(pdf_path)
    pages = _extract_text_pages(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        page1_obj = pdf.pages[0] if len(pdf.pages) >= 1 else None

        page1 = pages[0] if len(pages) >= 1 else ""
        page2 = pages[1] if len(pages) >= 2 else ""
        all_text = "\n".join(pages)

        page1_lines = _clean_lines(page1)
        page2_lines = _clean_lines(page2)
        all_lines = _clean_lines(all_text)

        company_name = None
        account_no = None
        invoice_no = None
        bill_date = None
        period_start = None
        period_end = None
        no_of_days = None
        tariff_desc = None
        address = None
        state = None
        security_deposit_rm = None
        payment_period_start = None
        payment_period_end = None
        payment_amount_rm = None
        total_bill_rm = None

        company_name, address, state = _extract_company_address_from_page1(page1_obj, page1_lines)

        if page1_obj is not None:
            bill_date_lines = _extract_region_lines(page1_obj, 220, 65, 360, 100)
            bill_date_line = _first_line_matching(bill_date_lines, r"\d{2}\.\d{2}\.\d{4}")
            bill_date = _parse_date_any(bill_date_line)

        if bill_date is None:
            bill_date_line = _next_matching_line(
                all_lines,
                r"TARIKH\s+BIL",
                r"\d{2}[./-]\d{2}[./-]\d{4}",
                max_lookahead=5,
            )
            bill_date = _parse_date_any(bill_date_line)

        if page1_obj is not None:
            period_lines = _extract_region_lines(page1_obj, 220, 90, 390, 145)
            period_text = " ".join(period_lines)
            period_start, period_end, no_of_days = _parse_date_range_and_days_from_text(period_text)

        if period_start is None or period_end is None or no_of_days is None:
            label_idx = _find_line_index(all_lines, r"TEMPOH\s+BIL")

            if label_idx is not None:
                block = "\n".join(all_lines[label_idx + 1 : label_idx + 8])
                p_start, p_end, p_days = _parse_date_range_and_days_from_text(block)

                period_start = period_start or p_start
                period_end = period_end or p_end
                no_of_days = no_of_days or p_days

        if period_start is None or period_end is None or no_of_days is None:
            fallback_match = re.search(
                r"TEMPOH\s*BIL.*?(\d{2}[./-]\d{2}[./-]\d{4})\s*-\s*(\d{2}[./-]\d{2}[./-]\d{4}).*?\((\d+)\s*Hari\)",
                all_text,
                re.I | re.S,
            )

            if fallback_match:
                period_start = period_start or _parse_date_any(fallback_match.group(1))
                period_end = period_end or _parse_date_any(fallback_match.group(2))
                no_of_days = no_of_days or int(fallback_match.group(3))

        if page1_obj is not None:
            invoice_lines = _extract_region_lines(page1_obj, 220, 140, 380, 170)
            invoice_line = _first_line_matching(invoice_lines, r"\d{6,}")
            if invoice_line:
                match = re.search(r"(\d{6,})", invoice_line)
                invoice_no = match.group(1) if match else None

        if invoice_no is None:
            invoice_line = _next_matching_line(
                all_lines,
                r"NO\.\s*INVOIS",
                r"\d{6,}",
                max_lookahead=5,
            )
            if invoice_line:
                match = re.search(r"(\d{6,})", invoice_line)
                invoice_no = match.group(1) if match else None

        if page1_obj is not None:
            account_lines = _extract_region_lines(page1_obj, 380, 65, 590, 105)
            account_line = _first_line_matching(account_lines, r"\d{6,}")
            if account_line:
                match = re.search(r"(\d{6,})", account_line)
                account_no = match.group(1) if match else None

        if account_no is None:
            account_line = _next_matching_line(
                all_lines,
                r"NO\.\s*AKAUN",
                r"\d{6,}",
                max_lookahead=8,
            )
            if account_line:
                match = re.search(r"(\d{6,})", account_line)
                account_no = match.group(1) if match else None

        if page1_obj is not None:
            tariff_lines = _extract_region_lines(page1_obj, 380, 135, 610, 170)
            tariff_desc = tariff_lines[0] if tariff_lines else None

        if not tariff_desc:
            tariff_line = _next_matching_line(
                all_lines,
                r"TARIF",
                r"Bukan\s+Domestik|Domestik|Tarif",
                max_lookahead=6,
            )
            tariff_desc = tariff_line

        security_deposit_rm = _extract_security_deposit(
            page1_obj=page1_obj,
            page1_lines=page1_lines,
            all_lines=all_lines,
            page1_text=page1,
            all_text=all_text,
        )

        payment_period_start, payment_period_end, payment_amount_rm = _extract_payment_for_period_and_amount(
            page1_obj=page1_obj,
            page1_lines=page1_lines,
            all_lines=all_lines,
            page1_text=page1,
            all_text=all_text,
            billing_start=period_start,
            billing_end=period_end,
        )

        if page1_obj is not None:
            total_bill_lines = _extract_region_lines(page1_obj, 15, 310, 190, 365)
            total_bill_line = _first_line_matching(total_bill_lines, r"[\d,]+\.\d{2}")
            total_bill_rm = _parse_num(total_bill_line) if total_bill_line else None

        if total_bill_rm is None:
            total_bill_line = _next_matching_line(
                all_lines,
                r"Jumlah\s+Bil\s+Anda\s*\(RM\)",
                r"[\d,]+\.\d{2}",
                max_lookahead=6,
            )
            total_bill_rm = _parse_num(total_bill_line) if total_bill_line else None

        utility_match = re.search(r"Utility\s+RM\s*([\d,]+\.\d{2})", all_text, re.I)
        utility_rm = _parse_rm(utility_match.group(1)) if utility_match else None

        detail_rows = _extract_charge_rows(page2_lines, page2)
        history = _extract_six_month_history(page1)

        if period_end is not None:
            current_row = None

            for row in history:
                if row.year == period_end.year and row.month == period_end.month:
                    current_row = row
                    break

            if current_row is None:
                current_row = MonthlyHistoryRow(
                    month=period_end.month,
                    year=period_end.year,
                    month_label=f"{MONTH_LABEL_EN[period_end.month]}-{str(period_end.year)[-2:]}",
                )
                history.append(current_row)

            if total_bill_rm is not None:
                current_row.total_tnb_monthly_bill_rm = total_bill_rm

            if detail_rows["total_usage_kwh"] is not None:
                current_row.total_usage_kwh = detail_rows["total_usage_kwh"]

        history.sort(key=lambda x: (x.year, x.month))

        return ParsedTnbBill(
            company_name=company_name,
            account_no=account_no,
            invoice_no=invoice_no,
            bill_date=bill_date,
            period_start=period_start,
            period_end=period_end,
            no_of_days=no_of_days,
            tariff_desc=tariff_desc,
            address=address,
            state=state,
            security_deposit_rm=security_deposit_rm,
            payment_period_start=payment_period_start,
            payment_period_end=payment_period_end,
            payment_amount_rm=payment_amount_rm,
            total_bill_rm=total_bill_rm,
            utility_rm=utility_rm,
            current_month_charge_rm=detail_rows["current_month_charge_rm"],
            kwtbb_rm=detail_rows["kwtbb_rm"],
            peak_usage_kwh=detail_rows["peak_usage_kwh"],
            offpeak_usage_kwh=detail_rows["offpeak_usage_kwh"],
            total_usage_kwh=detail_rows["total_usage_kwh"],
            max_demand_kw=detail_rows["max_demand_kw"],
            afa_rm=detail_rows["afa_rm"],
            peak_tariff_rm=detail_rows["peak_tariff_rm"],
            offpeak_tariff_rm=detail_rows["offpeak_tariff_rm"],
            capacity_charge_rm=detail_rows["capacity_charge_rm"],
            network_charge_rm=detail_rows["network_charge_rm"],
            retail_charge_rm=detail_rows["retail_charge_rm"],
            history=history,
            raw_pages=pages,
        )