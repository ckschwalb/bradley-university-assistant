"""
Times are stored in UTC and converted to local time only for display.

Database columns hold UTC (see models.UTCDateTime), and the API sends every time with its offset,
so the browser shows it in the viewer's own time zone. Times kept in settings are ISO strings
with their offset (utc_iso). Central time (Bradley's campus in Peoria) is used in one place: the
date the assistant is told it is today, so deadline questions are answered by the campus calendar.
"""

from datetime import UTC, datetime

import pytz

CENTRAL = pytz.timezone("America/Chicago")


def utc_now() -> datetime:
    """The current time in UTC, with its offset attached"""
    return datetime.now(UTC)


def utc_iso() -> str:
    return utc_now().isoformat()


def parse_iso(value: str) -> datetime:
    """An ISO time from settings as an aware datetime; one without an offset is read as UTC"""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def campus_now() -> datetime:
    """The current time on Bradley's campus (Central)"""
    return datetime.now(CENTRAL)
