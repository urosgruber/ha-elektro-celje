"""Ready-made texts for the dashboard card.

The card only loops and prints. This module builds all the texts, in
Slovenian or English, with times in Europe/Ljubljana.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from .const import PROBLEM_AFTER_SECONDS, TZ
from .location import LocationData
from .models import Outage
from .outages import is_active, is_ended_today

TEXT_LIMIT = 120
UNKNOWN_SORT = "9999-12-31T00:00:00+00:00"

TEXTS: dict[str, dict[str, Any]] = {
    "en": {
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "months": [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
        "date": "{weekday} {day} {month}",
        "date_year": "{weekday} {day} {month} {year}",
        "today": "today",
        "tomorrow": "tomorrow",
        "in_days": "in {n} days",
        "Today": "Today",
        "Tomorrow": "Tomorrow",
        "all_day": "all day",
        "unknown_time": "time unknown",
        "unknown_day": "Date unknown",
        "now": "Outage now",
        "until": "until {time}",
        "ended": "ended",
        "h": "h",
        "min": "min",
        "also_planned": "Also planned",
        "ended_today": "Ended today",
        "checked": "Checked",
        "feed_error": "Cannot read the Elektro Celje feed.",
        "last_good": "Last good check: {when}.",
        "list_old": "The list below may be old.",
        "problem_title": "Cannot read the Elektro Celje feed",
        "problem_detail": "Last good check: {when} · the list below may be old",
        "ends_in": "ends in {d}",
        "hours_minutes": "{h} h {m} min",
        "hours": "{h} h",
        "minutes": "{m} min",
    },
    "sl": {
        "weekdays": ["pon", "tor", "sre", "čet", "pet", "sob", "ned"],
        "months": [
            "jan",
            "feb",
            "mar",
            "apr",
            "maj",
            "jun",
            "jul",
            "avg",
            "sep",
            "okt",
            "nov",
            "dec",
        ],
        "date": "{weekday} {day}. {month}",
        "date_year": "{weekday} {day}. {month} {year}",
        "today": "danes",
        "tomorrow": "jutri",
        "in_days": "čez {n} dni",
        "Today": "Danes",
        "Tomorrow": "Jutri",
        "all_day": "ves dan",
        "unknown_time": "čas ni znan",
        "unknown_day": "Datum ni znan",
        "now": "Izklop zdaj",
        "until": "do {time}",
        "ended": "končano",
        "h": "h",
        "min": "min",
        "also_planned": "Še načrtovani izklopi",
        "ended_today": "Danes končani izklopi",
        "checked": "Preverjeno",
        "feed_error": "Podatkov Elektro Celje ni mogoče prebrati.",
        "last_good": "Zadnje uspešno preverjanje: {when}.",
        "list_old": "Spodnji seznam je morda zastarel.",
        "problem_title": "Podatkov Elektro Celje ni mogoče prebrati",
        "problem_detail": (
            "Zadnje uspešno preverjanje: {when} · spodnji seznam je morda zastarel"
        ),
        "ends_in": "konča se čez {d}",
        "hours_minutes": "{h} h {m} min",
        "hours": "{h} h",
        "minutes": "{m} min",
    },
}


def texts_for(language: str) -> dict[str, Any]:
    """Return the text table. Slovenian for `sl`, English otherwise."""
    return TEXTS["sl" if language.lower().startswith("sl") else "en"]


def _date(d: date, t: dict[str, Any], year: bool = False) -> str:
    return t["date_year" if year else "date"].format(
        weekday=t["weekdays"][d.weekday()],
        day=d.day,
        month=t["months"][d.month - 1],
        year=d.year,
    )


def _local(moment: datetime) -> datetime:
    return moment.astimezone(TZ)


def _clock(o: Outage, t: dict[str, Any]) -> str:
    if o.all_day:
        return t["all_day"]
    assert o.start is not None
    end = f"{_local(o.end):%H:%M}" if o.end else "?"
    return f"{_local(o.start):%H:%M}–{end}"


def _duration(o: Outage, t: dict[str, Any]) -> str:
    """Return the real length of a timed outage, or an empty text."""
    if o.all_day or o.start is None or o.end is None:
        return ""
    elapsed = o.end.astimezone(UTC) - o.start.astimezone(UTC)
    minutes = int(elapsed.total_seconds() // 60)
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} {t['h']}")
    if rest:
        parts.append(f"{rest} {t['min']}")
    return " ".join(parts)


def _relative(days: int, t: dict[str, Any]) -> str:
    if days <= 0:
        return t["today"]
    if days == 1:
        return t["tomorrow"]
    return t["in_days"].format(n=days)


def _sort(o: Outage) -> str:
    if o.start is None:
        return UNKNOWN_SORT
    return o.start.astimezone(UTC).isoformat()


def _item(
    o: Outage, group: str, location: str, now: datetime, t: dict[str, Any]
) -> dict[str, Any]:
    local_now = _local(now)
    text = " ".join(o.text.split())[:TEXT_LIMIT]
    item: dict[str, Any] = {
        "location": location,
        "group": group,
        "sort": _sort(o),
    }
    if o.start is None:
        item.update(
            title=f"{t['unknown_day']} · {t['unknown_time']}",
            detail=text,
            day=t["unknown_day"],
            row=f"{t['unknown_time']} · {text}",
            span=f"{t['unknown_time']} · {text}",
            chip="",
        )
        return item
    start_day = _local(o.start).date()
    clock = _clock(o, t)
    day = _date(start_day, t)
    item["day"] = day
    if group == "live":
        item.update(
            title=f"{t['now']} · {clock}",
            detail=""
            if o.all_day or o.end is None
            else t["until"].format(time=f"{_local(o.end):%H:%M}"),
            row=clock,
            span=clock,
            chip="",
            # The card counts down to this moment in the browser.
            end=o.end.astimezone(UTC).isoformat() if o.end else None,
        )
        return item
    if group == "ended":
        item.update(
            title=f"{clock} · {t['ended']}", detail="", row=clock, span=clock, chip=""
        )
        return item
    days = (start_day - local_now.date()).days
    if days <= 0:
        title = f"{t['Today']} · {clock}"
    elif days == 1:
        title = f"{t['Tomorrow']}, {day} · {clock}"
    else:
        title = f"{day} · {clock}"
    relative = _relative(days, t)
    duration = _duration(o, t)
    item.update(
        title=title,
        detail=" · ".join(p for p in (duration, relative) if p),
        row=" · ".join(p for p in (clock, duration, relative) if p),
        span=" · ".join(p for p in (clock, duration) if p),
        chip=relative,
    )
    return item


def _when(moment: datetime, now: datetime, t: dict[str, Any]) -> str:
    local = _local(moment)
    if local.date() == _local(now).date():
        return f"{t['today']} {local:%H:%M}"
    return f"{_date(local.date(), t)}, {local:%H:%M}"


def build_card(
    data: LocationData, location: str, now: datetime, language: str
) -> dict[str, Any]:
    """Return the card attributes of one location."""
    t = texts_for(language)
    items: list[dict[str, Any]] = []
    for o in data.planned:
        group = "live" if is_active(o, now) else "next"
        items.append(_item(o, group, location, now, t))
    for o in data.outages:
        if is_ended_today(o, now):
            items.append(_item(o, "ended", location, now, t))
    order = {"live": 0, "next": 1, "ended": 2}
    items.sort(key=lambda i: (order[i["group"]], i["sort"]))

    footer = None
    if data.last_success:
        stamp = _date(_local(data.last_success).date(), t, year=True)
        clock = f"{_local(data.last_success):%H:%M}"
        footer = f"{t['checked']} {stamp}, {clock} · elektro-celje.si"
    problem = problem_title = problem_detail = None
    since = data.problem_since
    if since and (now - since).total_seconds() > PROBLEM_AFTER_SECONDS:
        when = _when(data.last_success, now, t) if data.last_success else "–"
        problem = (
            f"{t['feed_error']} {t['last_good'].format(when=when)} {t['list_old']}"
        )
        problem_title = t["problem_title"]
        problem_detail = t["problem_detail"].format(when=when)
    return {
        "card": items,
        "card_footer": footer,
        "card_problem": problem,
        "card_problem_title": problem_title,
        "card_problem_detail": problem_detail,
        "card_labels": {
            "also_planned": t["also_planned"],
            "ended_today": t["ended_today"],
            "now": t["now"],
            "ends_in": t["ends_in"],
            "hours_minutes": t["hours_minutes"],
            "hours": t["hours"],
            "minutes": t["minutes"],
        },
    }
