"""S3MP's canonical business time zone helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

POSTGRES_TIMEZONE = "Asia/Shanghai"
# China has no daylight-saving changes.  A fixed offset keeps the application
# portable to minimal containers and Windows installations without tzdata.
CHINA_TIMEZONE = timezone(timedelta(hours=8), name=POSTGRES_TIMEZONE)


def to_china_time(value: datetime) -> datetime:
    """Return an aware datetime expressed in the system business time zone."""
    if value.tzinfo is None:
        return value
    return value.astimezone(CHINA_TIMEZONE)
