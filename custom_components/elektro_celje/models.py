"""Data models for parsed outage notices."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ParseStatus(StrEnum):
    """How well the parser read the date and time of a notice."""

    OK = "ok"
    DATE_ONLY = "date_only"
    FAILED = "failed"


@dataclass(frozen=True)
class Interval:
    """One period without power."""

    start: datetime
    end: datetime
    all_day: bool = False


@dataclass(frozen=True)
class Notice:
    """One outage notice from a feed."""

    notice_id: str
    region: str
    title: str
    link: str
    station_text: str | None
    station_names: tuple[str, ...]
    text: str
    date_texts: tuple[str, ...]
    intervals: tuple[Interval, ...]
    status: ParseStatus
    reason: str | None


@dataclass(frozen=True)
class Outage:
    """One outage of one location.

    A notice with status FAILED gives one outage with no start and no end.
    """

    key: str
    notice_id: str
    region: str
    station_text: str | None
    text: str
    link: str
    status: ParseStatus
    start: datetime | None
    end: datetime | None
    all_day: bool
