"""Decide which alerts to fire. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Any, Literal

from .const import (
    EVENT_OUTAGE_CHANGED,
    EVENT_OUTAGE_DETECTED,
    EVENT_OUTAGE_REMINDER,
    EVENT_OUTAGE_REMOVED,
    TZ,
)
from .models import Outage, ParseStatus
from .outages import is_planned, reminder_at

AlertKind = Literal["detected", "reminder", "changed", "removed"]

_EVENT_TYPES: dict[str, str] = {
    "detected": EVENT_OUTAGE_DETECTED,
    "reminder": EVENT_OUTAGE_REMINDER,
    "changed": EVENT_OUTAGE_CHANGED,
    "removed": EVENT_OUTAGE_REMOVED,
}


@dataclass
class OutageRecord:
    """An outage that the alert logic has seen. It has the fields of Outage."""

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
    first_seen: datetime
    reminder_sent: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict."""
        return {
            "key": self.key,
            "notice_id": self.notice_id,
            "region": self.region,
            "station_text": self.station_text,
            "text": self.text,
            "link": self.link,
            "status": self.status.value,
            "start": _iso(self.start),
            "end": _iso(self.end),
            "all_day": self.all_day,
            "first_seen": self.first_seen.isoformat(),
            "reminder_sent": self.reminder_sent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OutageRecord:
        """Build a record from the output of to_dict."""
        return cls(
            key=d["key"],
            notice_id=d["notice_id"],
            region=d["region"],
            station_text=d["station_text"],
            text=d["text"],
            link=d["link"],
            status=ParseStatus(d["status"]),
            start=_parse(d["start"]),
            end=_parse(d["end"]),
            all_day=d["all_day"],
            first_seen=datetime.fromisoformat(d["first_seen"]),
            reminder_sent=d["reminder_sent"],
        )


@dataclass(frozen=True)
class AlertEvent:
    """One alert to fire."""

    kind: AlertKind
    record: OutageRecord
    old_start: datetime | None = None
    old_end: datetime | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(TZ) if value else None


def _reminder_passed(
    record: OutageRecord | Outage, now: datetime, reminder: time
) -> bool:
    moment = reminder_at(record, reminder)
    return moment is not None and now >= moment


def _remind(
    rec: OutageRecord, now: datetime, reminder: time, events: list[AlertEvent]
) -> None:
    """Add a reminder event for the record if it is due. Mark it as sent."""
    moment = reminder_at(rec, reminder)
    if (
        moment is not None
        and rec.start is not None
        and moment <= now < rec.start
        and not rec.reminder_sent
    ):
        rec.reminder_sent = True
        events.append(AlertEvent("reminder", rec))


def evaluate(
    records: dict[str, OutageRecord],
    outages: list[Outage],
    now: datetime,
    ok_regions: set[str],
    reminder: time,
) -> tuple[list[AlertEvent], dict[str, OutageRecord]]:
    """Return the alerts to fire and the new records."""
    events: list[AlertEvent] = []
    result: dict[str, OutageRecord] = {}
    current = {o.key for o in outages}
    notice_ids = {o.notice_id for o in outages}

    for o in outages:
        if not is_planned(o, now):
            continue
        old = records.get(o.key)
        if old is None:
            rec = OutageRecord(
                key=o.key,
                notice_id=o.notice_id,
                region=o.region,
                station_text=o.station_text,
                text=o.text,
                link=o.link,
                status=o.status,
                start=o.start,
                end=o.end,
                all_day=o.all_day,
                first_seen=now,
                reminder_sent=_reminder_passed(o, now, reminder),
            )
            events.append(AlertEvent("detected", rec))
        else:
            changed = (old.start, old.end, old.status) != (o.start, o.end, o.status)
            rec = replace(
                old,
                station_text=o.station_text,
                text=o.text,
                link=o.link,
                status=o.status,
                start=o.start,
                end=o.end,
                all_day=o.all_day,
            )
            if changed:
                rec.reminder_sent = _reminder_passed(rec, now, reminder)
                events.append(AlertEvent("changed", rec, old.start, old.end))
        _remind(rec, now, reminder, events)
        result[o.key] = rec

    for key, rec in records.items():
        if key in current:
            continue
        if not is_planned(rec, now):
            continue
        if rec.notice_id in notice_ids:
            continue
        if rec.region not in ok_regions:
            kept = replace(rec)
            _remind(kept, now, reminder, events)
            result[key] = kept
            continue
        if rec.status is not ParseStatus.FAILED:
            events.append(AlertEvent("removed", rec))
    return events, result


def event_type(kind: str) -> str:
    """Return the Home Assistant event type for an alert kind."""
    return _EVENT_TYPES[kind]


def event_payload(event: AlertEvent, location: str, entry_id: str) -> dict[str, Any]:
    """Return the event data for an alert."""
    r = event.record
    duration = None
    if r.status is ParseStatus.OK and r.start and r.end:
        duration = int((r.end - r.start).total_seconds() // 60)
    payload: dict[str, Any] = {
        "location": location,
        "entry_id": entry_id,
        "notice_id": r.notice_id,
        "region": r.region,
        "station": r.station_text,
        "start": _iso(r.start),
        "end": _iso(r.end),
        "all_day": r.all_day,
        "duration_minutes": duration,
        "status": r.status.value,
        "text": r.text,
        "link": r.link,
    }
    if event.kind == "changed":
        payload["old_start"] = _iso(event.old_start)
        payload["old_end"] = _iso(event.old_end)
    return payload
