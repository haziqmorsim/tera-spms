from __future__ import annotations
from datetime import date
from pathlib import Path
from typing import Iterable
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from app.utils.time_utils import format_date_ddmmyyyy, format_datetime_gmt8

def _safe_text(value) -> str:
    if value is None:
        return "-"

    text = str(value).strip()
    return text if text else "-"

def _safe_num(value, digits: int = 2) -> str:
    if value is None:
        return "-"

    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return _safe_text(value)

def _escape_pdf_text(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def _cell_paragraph(
    text: str,
    style: ParagraphStyle,
    align: str = "LEFT",
) -> Paragraph:
    cell_style = ParagraphStyle(
        name=f"{style.name}_{align}",
        parent=style,
        alignment={
            "LEFT": 0,
            "CENTER": 1,
            "RIGHT": 2,
        }.get(align.upper(), 0),
        wordWrap="CJK",
    )

    return Paragraph(_escape_pdf_text(_safe_text(text)), cell_style)

def _build_table(
    data,
    col_widths,
    *,
    header_bg=colors.HexColor("#1ea5ff"),
    body_font_size=8.5,
    header_font_size=9,
):
    tbl = Table(data, colWidths=col_widths, repeatRows=1)

    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), header_font_size),
                ("FONTSIZE", (0, 1), (-1, -1), body_font_size),
                ("LEADING", (0, 0), (-1, -1), body_font_size + 2),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B7C0CC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    return tbl

def _append_warning_row(
    rows: list,
    *,
    message: str,
    column_count: int,
    style: ParagraphStyle,
) -> None:
    row = [_cell_paragraph(message, style, "CENTER")]

    for _ in range(column_count - 1):
        row.append(_cell_paragraph("", style))

    rows.append(row)

def build_troubleshooting_pdf(
    *,
    output_path: str | Path,
    report_day: date,
    generated_at,
    prepared_by: str,
    low_performing_plants: Iterable[dict],
    active_alarms: Iterable[dict],
    high_temperature_inverters: Iterable[dict],
    low_performing_inverters: Iterable[dict] | None = None,
    low_performing_strings: Iterable[dict] | None = None,
    section_warnings: dict[str, str] | None = None,
) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    left_right_margin = 10 * mm
    top_bottom_margin = 10 * mm
    page_width, _ = landscape(A4)
    usable_width = page_width - (left_right_margin * 2)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=left_right_margin,
        rightMargin=left_right_margin,
        topMargin=top_bottom_margin,
        bottomMargin=top_bottom_margin,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=colors.black,
        spaceAfter=8,
        alignment=1,
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=14,
        textColor=colors.black,
        spaceBefore=8,
        spaceAfter=6,
    )

    normal_style = ParagraphStyle(
        "NormalStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=12,
        spaceAfter=4,
        wordWrap="CJK",
    )

    table_body_style = ParagraphStyle(
        "TableBodyStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10,
        wordWrap="CJK",
    )

    table_header_style = ParagraphStyle(
        "TableHeaderStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=10.5,
        textColor=colors.white,
        wordWrap="CJK",
    )

    warning_style = ParagraphStyle(
        "WarningStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#B00020"),
        wordWrap="CJK",
    )

    low_performing_plants = list(low_performing_plants or [])
    active_alarms = list(active_alarms or [])
    high_temperature_inverters = list(high_temperature_inverters or [])
    low_performing_inverters = list(low_performing_inverters or [])
    low_performing_strings = list(low_performing_strings or [])
    section_warnings = section_warnings or {}

    story = []

    story.append(Paragraph("FusionSolar Troubleshooting Report", title_style))
    story.append(Spacer(1, 4))

    report_day_text = format_date_ddmmyyyy(report_day) if report_day else "-"
    generated_at_text = format_datetime_gmt8(generated_at) if generated_at else "-"

    story.append(
        Paragraph(
            f"<b>Date:</b> {_escape_pdf_text(report_day_text)}",
            normal_style,
        )
    )

    story.append(
        Paragraph(
            f"<b>Generated At:</b> {_escape_pdf_text(generated_at_text)}",
            normal_style,
        )
    )

    story.append(
        Paragraph(
            f"<b>Prepared By:</b> {_escape_pdf_text(_safe_text(prepared_by))}",
            normal_style,
        )
    )

    story.append(Spacer(1, 8))

    if section_warnings:
        story.append(Paragraph("Task Status Warnings", section_style))

        warning_rows = [
            [
                _cell_paragraph("Task", table_header_style, "CENTER"),
                _cell_paragraph("Status Message", table_header_style, "CENTER"),
            ]
        ]

        warning_labels = {
            "low_performing_plants": "Low-PSH Plants",
            "low_performing_inverters": "Low-performing Inverters",
            "low_performing_strings": "Low-performing Strings",
            "active_alarms": "Active Alarms",
            "high_temperature_inverters": "High-temperature Inverters",
        }

        for key, message in section_warnings.items():
            warning_rows.append(
                [
                    _cell_paragraph(warning_labels.get(key, key), table_body_style),
                    _cell_paragraph(message, warning_style),
                ]
            )

        story.append(
            _build_table(
                warning_rows,
                [usable_width * 0.28, usable_width * 0.72],
                body_font_size=8.5,
                header_font_size=9,
            )
        )

        story.append(Spacer(1, 10))

    story.append(Paragraph("Executive Summary", section_style))

    summary_rows = [
        [
            _cell_paragraph("Metric", table_header_style, "CENTER"),
            _cell_paragraph("Value", table_header_style, "CENTER"),
        ],
        [
            _cell_paragraph("Total low-performing plants", table_body_style),
            _cell_paragraph(str(len(low_performing_plants)), table_body_style, "CENTER"),
        ],
        [
            _cell_paragraph("Total low-performing inverters", table_body_style),
            _cell_paragraph(str(len(low_performing_inverters)), table_body_style, "CENTER"),
        ],
        [
            _cell_paragraph("Total low-performing strings", table_body_style),
            _cell_paragraph(str(len(low_performing_strings)), table_body_style, "CENTER"),
        ],
        [
            _cell_paragraph("Total alarms", table_body_style),
            _cell_paragraph(str(len(active_alarms)), table_body_style, "CENTER"),
        ],
        [
            _cell_paragraph("Total high-temperature inverters", table_body_style),
            _cell_paragraph(str(len(high_temperature_inverters)), table_body_style, "CENTER"),
        ],
        [
            _cell_paragraph("Unsuccessful task sections", table_body_style),
            _cell_paragraph(str(len(section_warnings)), table_body_style, "CENTER"),
        ],
    ]

    story.append(
        _build_table(
            summary_rows,
            [usable_width * 0.68, usable_width * 0.32],
            body_font_size=9,
            header_font_size=9,
        )
    )

    story.append(Spacer(1, 10))

    story.append(Paragraph("Low-performing Plants", section_style))

    low_rows = [
        [
            _cell_paragraph("Plant Name", table_header_style, "CENTER"),
            _cell_paragraph("Plant PSH", table_header_style, "CENTER"),
            _cell_paragraph("City Average PSH", table_header_style, "CENTER"),
            _cell_paragraph("Deviation", table_header_style, "CENTER"),
        ]
    ]

    if section_warnings.get("low_performing_plants"):
        _append_warning_row(
            low_rows,
            message=section_warnings["low_performing_plants"],
            column_count=4,
            style=warning_style,
        )

    elif low_performing_plants:
        for row in low_performing_plants:
            low_rows.append(
                [
                    _cell_paragraph(row.get("plant_name"), table_body_style),
                    _cell_paragraph(
                        _safe_num(row.get("plant_avg_psh"), 2),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("overall_avg_psh"), 2),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("psh_deviation_pct"), 2),
                        table_body_style,
                        "CENTER",
                    ),
                ]
            )

    else:
        low_rows.append(
            [
                _cell_paragraph("No low-performing plants found", table_body_style, "CENTER"),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
            ]
        )

    story.append(
        _build_table(
            low_rows,
            [
                usable_width * 0.46,
                usable_width * 0.16,
                usable_width * 0.20,
                usable_width * 0.18,
            ],
            body_font_size=8.5,
            header_font_size=9,
        )
    )

    story.append(Spacer(1, 10))

    story.append(Paragraph("Low-performing Inverters", section_style))

    inverter_rows = [
        [
            _cell_paragraph("Plant Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter SN", table_header_style, "CENTER"),
            _cell_paragraph("Inverter PSH", table_header_style, "CENTER"),
            _cell_paragraph("Benchmark PSH", table_header_style, "CENTER"),
            _cell_paragraph("Deviation", table_header_style, "CENTER"),
        ]
    ]

    if section_warnings.get("low_performing_inverters"):
        _append_warning_row(
            inverter_rows,
            message=section_warnings["low_performing_inverters"],
            column_count=6,
            style=warning_style,
        )

    elif low_performing_inverters:
        for row in low_performing_inverters:
            inverter_rows.append(
                [
                    _cell_paragraph(row.get("plant_name"), table_body_style),
                    _cell_paragraph(row.get("inverter_name"), table_body_style, "CENTER"),
                    _cell_paragraph(row.get("inverter_sn"), table_body_style, "CENTER"),
                    _cell_paragraph(
                        _safe_num(row.get("inverter_psh"), 3),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("benchmark_inverter_psh"), 3),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("deviation_pct_vs_benchmark"), 2),
                        table_body_style,
                        "CENTER",
                    ),
                ]
            )

    else:
        inverter_rows.append(
            [
                _cell_paragraph("No low-performing inverters found", table_body_style, "CENTER"),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
            ]
        )

    story.append(
        _build_table(
            inverter_rows,
            [
                usable_width * 0.27,
                usable_width * 0.13,
                usable_width * 0.18,
                usable_width * 0.13,
                usable_width * 0.14,
                usable_width * 0.15,
            ],
            body_font_size=7.8,
            header_font_size=8.3,
        )
    )

    story.append(Spacer(1, 10))

    story.append(Paragraph("Low-performing Strings", section_style))

    string_rows = [
        [
            _cell_paragraph("Plant Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter SN", table_header_style, "CENTER"),
            _cell_paragraph("String Name", table_header_style, "CENTER"),
            _cell_paragraph("Total Current", table_header_style, "CENTER"),
            _cell_paragraph("Benchmark", table_header_style, "CENTER"),
            _cell_paragraph("Deviation", table_header_style, "CENTER"),
        ]
    ]

    if section_warnings.get("low_performing_strings"):
        _append_warning_row(
            string_rows,
            message=section_warnings["low_performing_strings"],
            column_count=7,
            style=warning_style,
        )

    elif low_performing_strings:
        for row in low_performing_strings:
            string_rows.append(
                [
                    _cell_paragraph(row.get("plant_name"), table_body_style),
                    _cell_paragraph(row.get("inverter_name"), table_body_style, "CENTER"),
                    _cell_paragraph(row.get("inverter_sn"), table_body_style, "CENTER"),
                    _cell_paragraph(row.get("string_name"), table_body_style, "CENTER"),
                    _cell_paragraph(
                        _safe_num(row.get("string_total_current"), 3),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("benchmark_string_current"), 3),
                        table_body_style,
                        "CENTER",
                    ),
                    _cell_paragraph(
                        _safe_num(row.get("deviation_pct_vs_benchmark"), 2),
                        table_body_style,
                        "CENTER",
                    ),
                ]
            )

    else:
        string_rows.append(
            [
                _cell_paragraph("No low-performing strings found", table_body_style, "CENTER"),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
            ]
        )

    story.append(
        _build_table(
            string_rows,
            [
                usable_width * 0.24,
                usable_width * 0.11,
                usable_width * 0.17,
                usable_width * 0.18,
                usable_width * 0.10,
                usable_width * 0.10,
                usable_width * 0.10,
            ],
            body_font_size=7.5,
            header_font_size=8,
        )
    )

    story.append(Spacer(1, 10))

    story.append(Paragraph("Active Alarms", section_style))

    alarm_rows = [
        [
            _cell_paragraph("Plant Name", table_header_style, "CENTER"),
            _cell_paragraph("Device Name", table_header_style, "CENTER"),
            _cell_paragraph("Device SN", table_header_style, "CENTER"),
            _cell_paragraph("Alarm Name", table_header_style, "CENTER"),
            _cell_paragraph("Severity", table_header_style, "CENTER"),
            _cell_paragraph("Occurrence Time", table_header_style, "CENTER"),
        ]
    ]

    if section_warnings.get("active_alarms"):
        _append_warning_row(
            alarm_rows,
            message=section_warnings["active_alarms"],
            column_count=6,
            style=warning_style,
        )

    elif active_alarms:
        for row in active_alarms:
            alarm_rows.append(
                [
                    _cell_paragraph(row.get("plant_name"), table_body_style),
                    _cell_paragraph(row.get("device_name"), table_body_style),
                    _cell_paragraph(row.get("device_sn"), table_body_style, "CENTER"),
                    _cell_paragraph(row.get("alarm_name"), table_body_style),
                    _cell_paragraph(row.get("severity"), table_body_style, "CENTER"),
                    _cell_paragraph(row.get("occurrence_ts"), table_body_style, "CENTER"),
                ]
            )

    else:
        alarm_rows.append(
            [
                _cell_paragraph("No active alarms found", table_body_style, "CENTER"),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
            ]
        )

    story.append(
        _build_table(
            alarm_rows,
            [
                usable_width * 0.21,
                usable_width * 0.20,
                usable_width * 0.14,
                usable_width * 0.21,
                usable_width * 0.08,
                usable_width * 0.16,
            ],
            body_font_size=8,
            header_font_size=8.5,
        )
    )

    story.append(Spacer(1, 10))

    story.append(Paragraph("High-temperature Inverters", section_style))

    temp_rows = [
        [
            _cell_paragraph("Plant Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter Name", table_header_style, "CENTER"),
            _cell_paragraph("Inverter SN", table_header_style, "CENTER"),
            _cell_paragraph("Temperature", table_header_style, "CENTER"),
        ]
    ]

    if section_warnings.get("high_temperature_inverters"):
        _append_warning_row(
            temp_rows,
            message=section_warnings["high_temperature_inverters"],
            column_count=4,
            style=warning_style,
        )

    elif high_temperature_inverters:
        for row in high_temperature_inverters:
            temp_rows.append(
                [
                    _cell_paragraph(row.get("plant_name"), table_body_style),
                    _cell_paragraph(row.get("device_name"), table_body_style),
                    _cell_paragraph(row.get("device_sn"), table_body_style, "CENTER"),
                    _cell_paragraph(
                        _safe_num(row.get("internal_temperature_c"), 1),
                        table_body_style,
                        "CENTER",
                    ),
                ]
            )

    else:
        temp_rows.append(
            [
                _cell_paragraph("No high-temperature inverters found", table_body_style, "CENTER"),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
                _cell_paragraph("", table_body_style),
            ]
        )

    story.append(
        _build_table(
            temp_rows,
            [
                usable_width * 0.34,
                usable_width * 0.32,
                usable_width * 0.18,
                usable_width * 0.16,
            ],
            body_font_size=8.5,
            header_font_size=9,
        )
    )

    doc.build(story)

    return str(output_path)