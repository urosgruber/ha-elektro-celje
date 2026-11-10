"""Switches that turn the built-in notifications of one location on or off.

The switches gate the phone notifications only. The events always fire.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ElektroCeljeConfigEntry
from .const import ALERT_KINDS, DOMAIN
from .location import LocationCoordinator, switch_unique_id

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroCeljeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one switch for each alert kind."""
    coordinator = entry.runtime_data
    async_add_entities(NotifySwitch(coordinator, entry, kind) for kind in ALERT_KINDS)


class NotifySwitch(SwitchEntity, RestoreEntity):
    """Turn the notification of one alert kind on or off. Default: on."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: LocationCoordinator,
        entry: ElektroCeljeConfigEntry,
        kind: str,
    ) -> None:
        self._coordinator = coordinator
        self._kind = kind
        self._attr_translation_key = f"notify_{kind}"
        self._attr_unique_id = switch_unique_id(entry.entry_id, kind)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Elektro Celje",
            model="Planned outage notices (RSS)",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_is_on = coordinator.notify_enabled[kind]

    async def async_added_to_hass(self) -> None:
        """Restore the last state. A new switch is on."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._set(last.state == "on")

    def _set(self, value: bool) -> None:
        self._attr_is_on = value
        self._coordinator.notify_enabled[self._kind] = value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send this kind of notification."""
        self._set(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Do not send this kind of notification."""
        self._set(False)
        self.async_write_ha_state()
