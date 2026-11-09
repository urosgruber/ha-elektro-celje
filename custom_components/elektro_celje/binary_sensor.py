"""Binary sensors of the Elektro Celje integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroCeljeConfigEntry
from .entity import ElektroCeljeEntity, debug_attributes
from .outages import is_active

PARALLEL_UPDATES = 0

# Task 9 adds a module-level async_setup_platform here (YAML import).


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroCeljeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of one location."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            OutagePlannedSensor(coordinator, entry, "outage_planned"),
            OutageNowSensor(coordinator, entry, "outage_now"),
            FeedProblemSensor(coordinator, entry, "feed_problem"),
        ]
    )


class OutagePlannedSensor(ElektroCeljeEntity, BinarySensorEntity):
    """On when at least one outage is planned."""

    _unrecorded_attributes = frozenset({"outages", "feed_urls", "last_success"})

    @property
    def is_on(self) -> bool:
        """Return True if an outage is planned."""
        return len(self.data.planned) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the debug attributes."""
        return debug_attributes(self.data)


class OutageNowSensor(ElektroCeljeEntity, BinarySensorEntity):
    """On while the power is off."""

    @property
    def is_on(self) -> bool:
        """Return True if an outage is active now."""
        now = dt_util.utcnow()
        return any(is_active(o, now) for o in self.data.planned)


class FeedProblemSensor(ElektroCeljeEntity, BinarySensorEntity):
    """On when a feed cannot be read."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        """Return True if a feed has a problem."""
        return not self.data.feed_ok

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the time when the problem began."""
        since = self.data.problem_since
        return {"problem_since": since.isoformat() if since else None}
