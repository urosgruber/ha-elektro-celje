"""The Elektro Celje integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import ALL_REGIONS, CONF_REGION, REGIONS
from .coordinator import RegionCoordinator, async_acquire_region, async_release_region
from .location import LocationCoordinator, reminder_time

type ElektroCeljeConfigEntry = ConfigEntry[LocationCoordinator]

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR]


def _entry_regions(entry: ConfigEntry) -> list[str]:
    region = entry.data[CONF_REGION]
    return list(REGIONS) if region == ALL_REGIONS else [region]


async def async_setup_entry(
    hass: HomeAssistant, entry: ElektroCeljeConfigEntry
) -> bool:
    """Set up one location."""
    regions: list[RegionCoordinator] = []
    coordinator: LocationCoordinator | None = None
    try:
        for region in _entry_regions(entry):
            regions.append(await async_acquire_region(hass, region))
        coordinator = LocationCoordinator(hass, entry, regions)
        await coordinator.async_load()
        # A failed feed does not fail the setup. The location shows the problem.
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        if coordinator is not None:
            await coordinator.async_shutdown()
        for region in regions:
            await async_release_region(hass, region.region)
        raise

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        for region in coordinator.regions:
            await async_release_region(hass, region.region)
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ElektroCeljeConfigEntry
) -> bool:
    """Unload one location and release its region feeds."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = entry.runtime_data
    await coordinator.async_shutdown()
    for region in coordinator.regions:
        await async_release_region(hass, region.region)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ElektroCeljeConfigEntry
) -> None:
    """Reload the entry when the reminder time changes.

    Other updates, such as a reconfigure, reload the entry themselves.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.reminder == reminder_time(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)
