"""Parser for the Elektro Celje planned outage feeds."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

from .const import TZ
from .models import Interval, Notice, ParseStatus

MAX_FEED_BYTES = 1_000_000

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "avg": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}  # fmt: skip

_DATE_RE = re.compile(r"(\d{1,2})\.\s*([a-zčšž]+)\s+(\d{4})", re.IGNORECASE)
_DAY_TOKEN_RE = re.compile(r"(?<![\d:.])\d{1,2}\.(?!\d)")
_MED_RE = re.compile(r"med\s+(\d{1,2})[:.](\d{2})\s+in\s+(\d{1,2})[:.](\d{2})")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)")
_LINK_ID_RE = re.compile(r"/(\d+)-")
_BLOCK_TAGS = {"p", "br", "li", "ul", "div"}

_SEVERITY = {ParseStatus.OK: 0, ParseStatus.DATE_ONLY: 1, ParseStatus.FAILED: 2}


class FeedFormatError(Exception):
    """The feed is not an RSS document that the parser can read."""


def normalize(text: str) -> str:
    """Return text without accents, in lower case, with single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def notice_id_from(
    link: str, region: str, station_text: str | None, date_text: str
) -> str:
    """Return the numeric ID in the link, or a stable hash if it has none."""
    match = _LINK_ID_RE.search(urlparse(link).path)
    if match:
        return match.group(1)
    key = f"{region}|{station_text or ''}|{date_text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def split_station_names(station_text: str) -> tuple[str, ...]:
    """Split the station text into station names (the rules come later)."""
    return (station_text,)


class _DescriptionParser(HTMLParser):
    """Collect the station text, the date lines and the plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.station: str | None = None
        self.dates: list[str] = []
        self._text: list[str] = []
        self._in_strong = False
        self._strong: list[str] = []
        self._in_dates = False
        self._in_li = False
        self._li: list[str] = []

    @property
    def text(self) -> str:
        return " ".join("".join(self._text).split())

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self._text.append(" ")
        if tag == "ul" and "dates-list" in (dict(attrs).get("class") or "").split():
            self._in_dates = True
        elif tag == "li" and self._in_dates:
            self._in_li = True
            self._li = []
        elif tag == "strong":
            self._in_strong = True
            self._strong = []

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self._text.append(" ")
        if tag == "ul":
            self._in_dates = False
        elif tag == "li" and self._in_li:
            self._in_li = False
            line = " ".join("".join(self._li).split())
            if line:
                self.dates.append(line)
        elif tag == "strong" and self._in_strong:
            self._in_strong = False
            if self.station is None and not self._in_li and not self._in_dates:
                station = " ".join("".join(self._strong).split())
                self.station = station or None

    def handle_data(self, data):
        self._text.append(data)
        if self._in_strong:
            self._strong.append(data)
        if self._in_li:
            self._li.append(data)


def parse_schedule(
    line: str,
) -> tuple[ParseStatus, Interval | None, str | None]:
    """Read the date and time from the text of one list item."""
    matches = list(_DATE_RE.finditer(line))
    if not matches:
        return ParseStatus.FAILED, None, "no date found"
    if len(matches) > 1 or _DAY_TOKEN_RE.search(line[: matches[0].start()]):
        return ParseStatus.FAILED, None, "more than one date in one line"
    match = matches[0]
    month = MONTHS.get(match.group(2).lower()[:3])
    if month is None:
        return ParseStatus.FAILED, None, f"unknown month '{match.group(2)}'"
    try:
        day = datetime(int(match.group(3)), month, int(match.group(1)), tzinfo=TZ)
    except ValueError:
        return ParseStatus.FAILED, None, "date does not exist"

    med = _MED_RE.search(line)
    if med:
        sh, sm, eh, em = (int(g) for g in med.groups())
    else:
        times = _TIME_RE.findall(line[match.end() :])
        if len(times) < 2:
            return (
                ParseStatus.DATE_ONLY,
                Interval(day, day + timedelta(days=1), all_day=True),
                None,
            )
        (sh, sm), (eh, em) = ((int(h), int(m)) for h, m in times[:2])
    if sh > 23 or eh > 23 or sm > 59 or em > 59:
        return ParseStatus.FAILED, None, "time is not valid"

    start = day.replace(hour=sh, minute=sm)
    end = day.replace(hour=eh, minute=em)
    if end <= start:
        end += timedelta(days=1)
    return ParseStatus.OK, Interval(start, end), None


def _parse_item(item: ElementTree.Element, region: str) -> Notice:
    title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or "").strip()
    description = item.findtext("description") or ""
    if "<" not in description:
        description = html.unescape(description)
    parser = _DescriptionParser()
    parser.feed(description)
    parser.close()

    intervals: list[Interval] = []
    status = ParseStatus.OK
    reason: str | None = None
    for line in parser.dates:
        line_status, interval, line_reason = parse_schedule(line)
        if interval is not None:
            intervals.append(interval)
        if _SEVERITY[line_status] > _SEVERITY[status]:
            status = line_status
        if line_reason and reason is None:
            reason = line_reason
    if not parser.dates:
        status, reason = ParseStatus.FAILED, "no dates list in the notice"

    station = parser.station
    return Notice(
        notice_id=notice_id_from(link, region, station, "|".join(parser.dates)),
        region=region,
        title=title,
        link=link,
        station_text=station,
        station_names=split_station_names(station) if station else (),
        text=parser.text,
        date_texts=tuple(parser.dates),
        intervals=tuple(intervals),
        status=status,
        reason=reason,
    )


def parse_feed(xml_text: str, region: str) -> list[Notice]:
    """Parse one RSS feed into notices."""
    if len(xml_text.encode("utf-8")) > MAX_FEED_BYTES:
        raise FeedFormatError("feed is larger than 1 MB")
    if "<!ENTITY" in xml_text:
        raise FeedFormatError("feed declares XML entities")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as err:
        raise FeedFormatError(f"feed is not valid XML: {err}") from err
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise FeedFormatError("feed has no rss channel")
    return [_parse_item(item, region) for item in channel.findall("item")]
