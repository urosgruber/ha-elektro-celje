"""Coordinator that downloads one region feed for all entries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import FeedError, async_fetch_feed
from .const import DOMAIN, FEED_URL, SCAN_INTERVAL
from .models import Notice
from .parser import FeedFormatError, parse_feed

_LOGGER = logging.getLogger(__name__)


@dataclass
class RegionData:
    """The notices of one region after a good poll."""

    notices: list[Notice]
    fetched_at: datetime


class RegionCoordinator(DataUpdateCoordinator[RegionData]):
    """Poll the feed of one region."""

    def __init__(self, hass: HomeAssistant, region: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} {region}",
            update_interval=SCAN_INTERVAL,
        )
        self.region = region
        self.feed_url = FEED_URL.format(region=region)
        self.last_attempt: datetime | None = None
        self.last_success: datetime | None = None
        self.problem_since: datetime | None = None
        self._attempted = False

    async def _async_update_data(self) -> RegionData:
        now = dt_util.utcnow()
        self.last_attempt = now
        try:
            text = await async_fetch_feed(
                async_get_clientsession(self.hass), self.region
            )
            notices = parse_feed(text, self.region)
        except (FeedError, FeedFormatError) as err:
            if self.problem_since is None and (
                self.last_success is not None or not self._attempted
            ):
                self.problem_since = now
            self._attempted = True
            raise UpdateFailed(str(err)) from err
        self._attempted = True
        self.last_success = now
        self.problem_since = None
        return RegionData(notices=notices, fetched_at=now)


async def async_acquire_region(hass: HomeAssistant, region: str) -> RegionCoordinator:
    """Return the shared coordinator of a region and count the new user."""
    regions = hass.data.setdefault(DOMAIN, {}).setdefault("regions", {})
    entry = regions.get(region)
    if entry is None:
        coordinator = RegionCoordinator(hass, region)
        entry = regions[region] = {"coordinator": coordinator, "count": 1}
        # A coordinator polls only while it has a listener. This one keeps
        # polling alive until the last user releases the region.
        entry["unsub"] = coordinator.async_add_listener(lambda: None)
        await coordinator.async_refresh()
        return coordinator
    entry["count"] += 1
    return entry["coordinator"]


async def async_release_region(hass: HomeAssistant, region: str) -> None:
    """Drop one user of a region and shut the coordinator down at zero."""
    regions = hass.data.get(DOMAIN, {}).get("regions", {})
    entry = regions.get(region)
    if entry is None:
        return
    entry["count"] -= 1
    if entry["count"] <= 0:
        del regions[region]
        entry["unsub"]()
        await entry["coordinator"].async_shutdown()
