from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Kuala_Lumpur")


def now_gmt8() -> datetime:
    return datetime.now(APP_TZ)


def today_gmt8() -> date:
    return now_gmt8().date()


def to_gmt8(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(APP_TZ)


def format_date_ddmmyyyy(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = datetime.strptime(value, "%Y-%m-%d")

    if isinstance(value, datetime):
        value = to_gmt8(value).date() if value.tzinfo else value.date()

    return value.strftime("%d-%m-%Y")


def format_datetime_gmt8(value: datetime | str | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    value = to_gmt8(value)
    return value.strftime("%d-%m-%Y %H:%M:%S") if value else None


def format_unix_ts_gmt8(value: float | int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, APP_TZ).strftime("%d-%m-%Y %H:%M:%S")
