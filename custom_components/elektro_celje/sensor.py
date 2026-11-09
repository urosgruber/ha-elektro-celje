"""Sensors of the Elektro Celje integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroCeljeConfigEntry
from .cardtext import build_card
from .entity import ElektroCeljeEntity, debug_attributes, ended_today
from .location import LocationData
from .outages import days_until

PARALLEL_UPDATES = 0


def _first_with_start(data: LocationData):
    return next((o for o in data.planned if o.start is not None), None)


def _next_start(data: LocationData) -> datetime | None:
    outage = _first_with_start(data)
    return outage.start if outage else None


def _next_end(data: LocationData) -> datetime | None:
    outage = _first_with_start(data)
    return outage.end if outage else None


def _days_until(data: LocationData) -> int | None:
    if not data.planned:
        return None
    return days_until(data.planned[0], dt_util.utcnow())


@dataclass(frozen=True, kw_only=True)
class ElektroCeljeSensorDescription(SensorEntityDescription):
    """A sensor and the function that reads its value."""

    value_fn: Callable[[LocationData], Any]


SENSORS: tuple[ElektroCeljeSensorDescription, ...] = (
    ElektroCeljeSensorDescription(
        key="planned_outages",
        translation_key="planned_outages",
        value_fn=lambda d: len(d.planned),
    ),
    ElektroCeljeSensorDescription(
        key="next_outage_start",
        translation_key="next_outage_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_start,
    ),
    ElektroCeljeSensorDescription(
        key="next_outage_end",
        translation_key="next_outage_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_end,
    ),
    ElektroCeljeSensorDescription(
        key="days_until_outage",
        translation_key="days_until_outage",
        value_fn=_days_until,
    ),
    ElektroCeljeSensorDescription(
        key="last_checked",
        translation_key="last_checked",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_attempt,
    ),
    ElektroCeljeSensorDescription(
        key="last_successful_check",
        translation_key="last_successful_check",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_success,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroCeljeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of one location."""
    coordinator = entry.runtime_data
    async_add_entities(
        ElektroCeljeSensor(coordinator, entry, description) for description in SENSORS
    )


class ElektroCeljeSensor(ElektroCeljeEntity, SensorEntity):
    """A sensor of one location."""

    entity_description: ElektroCeljeSensorDescription
    _unrecorded_attributes = frozenset(
        {
            "outages",
            "ended_today",
            "feed_urls",
            "last_success",
            "card",
            "card_footer",
            "card_problem",
            "card_problem_title",
            "card_problem_detail",
            "card_labels",
        }
    )

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        return self.entity_description.value_fn(self.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the debug attributes of the planned_outages sensor."""
        if self.entity_description.key != "planned_outages":
            return None
        now = dt_util.utcnow()
        return {
            **debug_attributes(self.data),
            "ended_today": ended_today(self.data, now),
            **build_card(
                self.data, self._location_name(), now, self.hass.config.language
            ),
        }

    def _location_name(self) -> str:
        device = self.device_entry
        if device is not None:
            return (
                device.name_by_user
                or device.name
                or self.coordinator.config_entry.title
            )
        return self.coordinator.config_entry.title
