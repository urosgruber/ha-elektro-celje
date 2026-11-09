"""Coordinator that tracks the outages of one location and fires alerts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .alerts import OutageRecord, evaluate, event_payload, event_type
from .const import (
    CONF_REMINDER_TIME,
    CONF_STATION,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
    TZ,
)
from .coordinator import RegionCoordinator
from .models import Outage
from .outages import build_outages, is_planned, next_boundary

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def _store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


async def async_clear_alert_state(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the stored alert records of a config entry."""
    await _store(hass, entry_id).async_remove()


def reminder_time(entry: ConfigEntry) -> time:
    """Return the reminder time from the options of the entry."""
    value = entry.options.get(CONF_REMINDER_TIME)
    if not value:
        return DEFAULT_REMINDER_TIME
    try:
        return time.fromisoformat(value)
    except ValueError:
        _LOGGER.warning("Invalid reminder time %r, using the default", value)
        return DEFAULT_REMINDER_TIME


@dataclass
class LocationData:
    """The state of one location."""

    outages: list[Outage]
    planned: list[Outage]
    records: dict[str, OutageRecord]
    feed_urls: list[str]
    last_attempt: datetime | None
    last_success: datetime | None
    problem_since: datetime | None
    feed_ok: bool


def _to_outage(record: OutageRecord) -> Outage:
    return Outage(
        key=record.key,
        notice_id=record.notice_id,
        region=record.region,
        station_text=record.station_text,
        text=record.text,
        link=record.link,
        status=record.status,
        start=record.start,
        end=record.end,
        all_day=record.all_day,
    )


def _sort_key(outage: Outage) -> tuple[bool, datetime, str]:
    return (
        outage.start is None,
        outage.start or datetime.min.replace(tzinfo=TZ),
        outage.key,
    )


def _region_ok(region: RegionCoordinator) -> bool:
    return region.last_update_success and region.data is not None


class LocationCoordinator(DataUpdateCoordinator[LocationData]):
    """Combine the region feeds of one location and fire its alerts."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        regions: list[RegionCoordinator],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,
        )
        self.regions = regions
        self.query: str = entry.data[CONF_STATION]
        self.reminder = reminder_time(entry)
        self._store = _store(hass, entry.entry_id)
        self._records: dict[str, OutageRecord] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_regions: list[CALLBACK_TYPE] = []

    async def async_load(self) -> None:
        """Load the stored records and listen to the region coordinators."""
        stored = await self._store.async_load()
        if stored:
            for item in stored.get("records", []):
                try:
                    record = OutageRecord.from_dict(item)
                except (KeyError, TypeError, ValueError):
                    _LOGGER.warning("Skipping a stored record that is not valid")
                    continue
                self._records[record.key] = record
        self._unsub_regions = [
            region.async_add_listener(self._handle_region_update)
            for region in self.regions
        ]

    @callback
    def _handle_region_update(self) -> None:
        self._schedule_refresh_task()

    @callback
    def _handle_boundary(self, _now: datetime) -> None:
        self._unsub_timer = None
        self._schedule_refresh_task()

    @callback
    def _schedule_refresh_task(self) -> None:
        if self._shutdown_requested:
            return
        self.config_entry.async_create_task(
            self.hass, self.async_refresh(), f"{self.name} refresh"
        )

    async def _async_update_data(self) -> LocationData:
        async with self._lock:
            now = dt_util.utcnow()
            try:
                notices = [
                    notice
                    for region in self.regions
                    if region.data is not None
                    for notice in region.data.notices
                ]
                outages = build_outages(notices, self.query)
                ok_regions = {r.region for r in self.regions if _region_ok(r)}
                events, records = evaluate(
                    self._records, outages, now, ok_regions, self.reminder
                )
                self._records = records
                if self._closed:
                    # Shut down: another refresh owns the store now.
                    events = []
                else:
                    # Save before firing, so a crash between them cannot fire again.
                    await self._store.async_save(
                        {"records": [r.to_dict() for r in records.values()]}
                    )
                location = self.config_entry.title
                entry_id = self.config_entry.entry_id
                for event in events:
                    self.hass.bus.async_fire(
                        event_type(event.kind),
                        event_payload(event, location, entry_id),
                    )
                return self._location_data(
                    outages, self._planned(records, now), records
                )
            finally:
                # A failed run still schedules the next boundary.
                self._schedule_boundary(self._planned(self._records, now), now)

    @staticmethod
    def _planned(records: dict[str, OutageRecord], now: datetime) -> list[Outage]:
        return sorted(
            (_to_outage(r) for r in records.values() if is_planned(r, now)),
            key=_sort_key,
        )

    def _location_data(
        self,
        outages: list[Outage],
        planned: list[Outage],
        records: dict[str, OutageRecord],
    ) -> LocationData:
        attempts = [r.last_attempt for r in self.regions]
        successes = [r.last_success for r in self.regions]
        problems = [r.problem_since for r in self.regions if r.problem_since]
        return LocationData(
            outages=outages,
            planned=planned,
            records=dict(records),
            feed_urls=[r.feed_url for r in self.regions],
            last_attempt=None if None in attempts else min(attempts),
            last_success=None if None in successes else min(successes),
            problem_since=min(problems) if problems else None,
            feed_ok=all(_region_ok(r) for r in self.regions),
        )

    def _schedule_boundary(self, planned: list[Outage], now: datetime) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        if self._shutdown_requested:
            return
        when = next_boundary(planned, now, self.reminder)
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._handle_boundary, when
        )

    async def async_shutdown(self) -> None:
        """Stop the timer and the region listeners.

        Wait for a refresh in flight, then block the Store save and the events.
        """
        await super().async_shutdown()
        async with self._lock:
            self._closed = True
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        for unsub in self._unsub_regions:
            unsub()
        self._unsub_regions = []
