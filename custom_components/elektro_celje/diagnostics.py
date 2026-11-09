"""Diagnostics for the Elektro Celje integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ElektroCeljeConfigEntry
from .entity import outage_dict

TO_REDACT = {"name", "title", "station"}
# The matched notices show which station the user lives near. The key of an
# outage contains the notice ID, so it is redacted too.
LOCATION_REDACT = {"station", "station_text", "text", "link", "notice_id", "key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ElektroCeljeConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of one location.

    The region coordinator keeps parsed notices, not the raw XML. The
    `raw_items` section therefore lists the parsed fields of each notice.
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
        "outages": async_redact_data(
            [outage_dict(o) for o in data.outages], LOCATION_REDACT
        ),
        "planned": async_redact_data(
            [outage_dict(o) for o in data.planned], LOCATION_REDACT
        ),
        "records": async_redact_data(
            [r.to_dict() for r in data.records.values()], LOCATION_REDACT
        ),
        "feed_urls": data.feed_urls,
        "feed_ok": data.feed_ok,
    }
