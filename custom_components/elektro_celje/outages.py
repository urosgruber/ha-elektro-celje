"""Compute the state of outages for one location."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Protocol

from .const import TZ
from .matching import matches
from .models import Interval, Notice, Outage, ParseStatus


class OutageLike(Protocol):
    """Any record with the time fields of an outage."""

    status: ParseStatus
    start: datetime | None
    end: datetime | None
    all_day: bool


def build_outages(notices: Iterable[Notice], query: str) -> list[Outage]:
    """Return the outages of the notices that match the query.

    The result is sorted by start. Outages without a start come last.
    """
    result: list[Outage] = []
    for notice in notices:
        if not matches(query, notice):
            continue
        if notice.status is ParseStatus.FAILED:
            result.append(_outage(notice, 0, None))
            continue
        for index, interval in enumerate(notice.intervals):
            result.append(_outage(notice, index, interval))
    result.sort(
        key=lambda o: (o.start is None, o.start or datetime.min.replace(tzinfo=TZ))
    )
    return result


def _outage(notice: Notice, index: int, interval: Interval | None) -> Outage:
    return Outage(
        key=f"{notice.notice_id}:{index}",
        notice_id=notice.notice_id,
        region=notice.region,
        station_text=notice.station_text,
        text=notice.text,
        link=notice.link,
        # A FAILED notice has no interval here (ruling R8). Otherwise each
        # interval keeps the status of its own line.
        status=interval.status if interval else notice.status,
        start=interval.start if interval else None,
        end=interval.end if interval else None,
        all_day=interval.all_day if interval else False,
    )


def is_planned(o: OutageLike, now: datetime) -> bool:
    """Return True if the outage is not over. A FAILED outage is always planned."""
    if o.status is ParseStatus.FAILED or o.end is None:
        return True
    return o.end > now


def is_active(o: OutageLike, now: datetime) -> bool:
    """Return True if power is off now. Only an OK outage can be active."""
    if o.status is not ParseStatus.OK or o.start is None or o.end is None:
        return False
    return o.start <= now < o.end


def days_until(o: OutageLike, now: datetime) -> int | None:
    """Return the number of local dates until the outage, at least 0."""
    if o.status is ParseStatus.FAILED or o.start is None:
        return None
    delta = o.start.astimezone(TZ).date() - now.astimezone(TZ).date()
    return max(delta.days, 0)


def reminder_at(o: OutageLike, reminder: time) -> datetime | None:
    """Return the reminder moment: the local day before the start, at `reminder`."""
    if o.status is ParseStatus.FAILED or o.start is None:
        return None
    day = o.start.astimezone(TZ).date() - timedelta(days=1)
    return datetime.combine(day, reminder, tzinfo=TZ)


def next_boundary(
    outages: list[Outage],
    now: datetime,
    reminder: time,
    extra: Iterable[datetime] = (),
) -> datetime:
    """Return the earliest future moment when the state can change.

    `extra` holds other moments that matter, such as the end of the grace
    period of a feed problem.
    """
    local_now = now.astimezone(TZ)
    midnight = datetime.combine(
        local_now.date() + timedelta(days=1), time(0), tzinfo=TZ
    )
    candidates = [midnight, *extra]
    for o in outages:
        candidates.extend([o.start, o.end, reminder_at(o, reminder)])
    return min(c for c in candidates if c is not None and c > now)


def is_ended_today(o: OutageLike, now: datetime) -> bool:
    """Return True if an OK or date-only outage ended earlier on the local day.

    The last instant of the outage decides the day. An outage that ends at
    00:00 belongs to the day before, so it is never "ended today".
    """
    if o.status is ParseStatus.FAILED or o.end is None or o.end > now:
        return False
    last = o.end - timedelta(microseconds=1)
    return last.astimezone(TZ).date() == now.astimezone(TZ).date()
