"""Diagnostics for the Elektro Celje integration."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ElektroCeljeConfigEntry
from .entity import outage_dict

TO_REDACT = {"name", "title", "station", "notify_targets", "quiet_entity"}


def _summary(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: item[key] for key in keys}


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(item["status"] for item in items))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ElektroCeljeConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of one location.

    The region coordinator keeps parsed notices, not the raw XML. The
    `raw_items` section therefore lists the parsed fields of each notice. The
    region feeds are public.

    The location sections show only the status, the all-day flag, the reminder
    flag and the count per status (ruling R20). A time, a region or a notice ID
    of an outage of this location could be matched to one raw item. That item
    shows the station, and the station shows where the user lives.
    """
    coordinator = entry.runtime_data
    data = coordinator.data
    raw_items = {
        region.region: [
            {
                "title": notice.title,
                "link": notice.link,
                "text": notice.text,
                "date_texts": list(notice.date_texts),
                "station_text": notice.station_text,
                "status": notice.status.value,
                "reason": notice.reason,
            }
            for notice in (region.data.notices if region.data else [])
        ]
        for region in coordinator.regions
    }
    outage_keys = ("status", "all_day")
    record_keys = ("status", "all_day", "reminder_sent")
    outages = [_summary(outage_dict(o), outage_keys) for o in data.outages]
    planned = [_summary(outage_dict(o), outage_keys) for o in data.planned]
    records = [_summary(r.to_dict(), record_keys) for r in data.records.values()]
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "raw_items": raw_items,
        "outages": outages,
        "planned": planned,
        "records": records,
        "status_counts": {
            "outages": _status_counts(outages),
            "planned": _status_counts(planned),
            "records": _status_counts(records),
        },
        "feed_urls": data.feed_urls,
        "feed_ok": data.feed_ok,
    }
