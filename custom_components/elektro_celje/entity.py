"""Base class of the Elektro Celje entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .location import LocationCoordinator, LocationData
from .models import Outage
from .outages import is_ended_today

TEXT_LIMIT = 300


def outage_dict(outage: Outage) -> dict[str, Any]:
    """Return an outage as a JSON-safe dict for the `outages` attribute."""
    return {
        "start": outage.start.isoformat() if outage.start else None,
        "end": outage.end.isoformat() if outage.end else None,
        "all_day": outage.all_day,
        "status": outage.status.value,
        "station": outage.station_text,
        "region": outage.region,
        "text": outage.text[:TEXT_LIMIT],
        "link": outage.link,
    }


def ended_today(data: LocationData, now: datetime) -> list[dict[str, Any]]:
    """Return the listed outages that ended earlier on the local date of `now`."""
    return [outage_dict(o) for o in data.outages if is_ended_today(o, now)]


def debug_attributes(data: LocationData) -> dict[str, Any]:
    """Return the attributes that the planned entities share."""
    return {
        "outages": [outage_dict(o) for o in data.planned],
        "feed_urls": data.feed_urls,
        "last_success": data.last_success.isoformat() if data.last_success else None,
    }


class ElektroCeljeEntity(CoordinatorEntity[LocationCoordinator]):
    """An entity of one location."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LocationCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Elektro Celje",
            model="Planned outage notices (RSS)",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Stay available when the feed fails. The entity keeps the last data."""
        return self.coordinator.data is not None

    @property
    def data(self) -> LocationData:
        """Return the data of the location."""
        return self.coordinator.data
