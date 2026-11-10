"""Coordinator that tracks the outages of one location and fires alerts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .alerts import AlertEvent, OutageRecord, evaluate, event_payload, event_type
from .const import (
    ALERT_KINDS,
    CONF_REMINDER_TIME,
    CONF_STATION,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
    PROBLEM_AFTER_SECONDS,
    TZ,
)
from .coordinator import RegionCoordinator
from .models import Outage
from .notifications import (
    NotifySettings,
    async_send,
    has_ended,
    make_item,
    merge,
    quiet_state,
    starts_before,
    valid_item,
)
from .outages import build_outages, is_planned, next_boundary

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def _store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


async def async_clear_alert_state(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the stored alert records of a config entry."""
    await _store(hass, entry_id).async_remove()


def switch_unique_id(entry_id: str, kind: str) -> str:
    """Return the unique ID of the notification switch of an alert kind."""
    return f"{entry_id}_notify_{kind}"


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
        # A change of any option reloads the entry (see the update listener).
        self.options: dict[str, Any] = dict(entry.options)
        self.notify = NotifySettings.from_options(entry.options)
        # The notification switches write here. They gate sending only.
        self.notify_enabled: dict[str, bool] = dict.fromkeys(ALERT_KINDS, True)
        self._store = _store(hass, entry.entry_id)
        self._records: dict[str, OutageRecord] = {}
        # Alerts that wait for the end of the quiet hours, by outage key.
        self._held: dict[str, dict[str, Any]] = {}
        self._unsub_flush: CALLBACK_TYPE | None = None
        self._unsub_quiet_entity: CALLBACK_TYPE | None = None
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
            held = stored.get("held") or {}
            if isinstance(held, dict):
                self._held = {
                    key: item for key, item in held.items() if valid_item(item)
                }
        self._restore_switches()
        if self.notify.quiet_hours and self.notify.quiet_entity:
            self._unsub_quiet_entity = async_track_state_change_event(
                self.hass, [self.notify.quiet_entity], self._handle_quiet_entity
            )
        self._unsub_regions = [
            region.async_add_listener(self._handle_region_update)
            for region in self.regions
        ]

    def _restore_switches(self) -> None:
        """Read the last switch states before the first refresh.

        The switch entities restore themselves later, after the first refresh.
        The first refresh must already respect a switch that the user turned off.
        """
        registry = er.async_get(self.hass)
        last_states = restore_state.async_get(self.hass).last_states
        for kind in ALERT_KINDS:
            entity_id = registry.async_get_entity_id(
                "switch", DOMAIN, switch_unique_id(self.config_entry.entry_id, kind)
            )
            stored = last_states.get(entity_id) if entity_id else None
            if stored is not None:
                self.notify_enabled[kind] = stored.state.state != "off"

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
                # A suspect empty read keeps the records, as a failed read does,
                # but it is not a feed problem (ruling R21).
                ok_regions = {
                    r.region
                    for r in self.regions
                    if _region_ok(r) and not r.suspect_empty
                }
                events, records = evaluate(
                    self._records, outages, now, ok_regions, self.reminder
                )
                self._records = records
                to_send: list[dict[str, Any]] = []
                if self._closed:
                    # Shut down: another refresh owns the store now.
                    events = []
                else:
                    to_send = self._route(events, now)
                    # Save before firing, so a crash between them cannot fire again.
                    await self._async_save()
                location = self.config_entry.title
                entry_id = self.config_entry.entry_id
                for event in events:
                    self.hass.bus.async_fire(
                        event_type(event.kind),
                        event_payload(event, location, entry_id),
                    )
                self._start_send(to_send)
                self._arm_flush(now)
                return self._location_data(
                    outages, self._planned(records, now), records
                )
            finally:
                # A failed run still schedules the next boundary.
                self._schedule_boundary(self._planned(self._records, now), now)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "records": [r.to_dict() for r in self._records.values()],
                "held": self._held,
            }
        )

    # --- Notifications -----------------------------------------------------

    def _route(self, events: list[AlertEvent], now: datetime) -> list[dict[str, Any]]:
        """Hold or pass each alert. Return the alerts to send now.

        The events themselves fire in any case. This decides the phones only.
        """
        if not self.notify.targets:
            return []
        quiet = quiet_state(self.hass, self.notify, now)
        location = self.config_entry.title
        entry_id = self.config_entry.entry_id
        to_send: list[dict[str, Any]] = []
        for event in events:
            new = make_item(event.kind, event_payload(event, location, entry_id))
            key = event.record.key
            held = self._held.pop(key, None)
            item = merge(held, new)
            if item is not None and not self.notify_enabled[item["kind"]]:
                # A reminder that is off must not discard a held alert.
                item = held if new["kind"] == "reminder" else None
            if item is None:
                continue
            # An outage that starts before the quiet hours end cannot wait.
            if quiet.quiet and not starts_before(item, quiet.end):
                self._held[key] = item
            else:
                to_send.append(item)
        return to_send

    @callback
    def _start_send(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        self.config_entry.async_create_task(
            self.hass, self._async_send(items), f"{self.name} notify"
        )

    async def _async_send(self, items: list[dict[str, Any]]) -> None:
        entry_id = self.config_entry.entry_id
        for item in items:
            # The user can turn a switch off while an alert waits.
            if not self.notify_enabled[item["kind"]]:
                continue
            await async_send(self.hass, self.notify.targets, entry_id, item)

    @callback
    def _arm_flush(self, now: datetime) -> None:
        """Send the held alerts now, or set a timer for the end of the quiet hours.

        In entity mode the state listener flushes. It needs no timer.
        """
        if self._unsub_flush is not None:
            self._unsub_flush()
            self._unsub_flush = None
        if not self._held or self._closed or self._shutdown_requested:
            return
        quiet = quiet_state(self.hass, self.notify, now)
        if not quiet.quiet:
            self.config_entry.async_create_task(
                self.hass, self.async_flush(), f"{self.name} flush"
            )
        elif not self.notify.quiet_entity and quiet.end is not None:
            # Never a moment in the past: that would loop the timer.
            when = max(quiet.end, now + timedelta(seconds=1))
            self._unsub_flush = async_track_point_in_utc_time(
                self.hass, self._handle_flush_time, when
            )

    @callback
    def _handle_flush_time(self, _now: datetime) -> None:
        self._unsub_flush = None
        self.config_entry.async_create_task(
            self.hass, self.async_flush(), f"{self.name} flush"
        )

    @callback
    def _handle_quiet_entity(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is not None and new_state.state == "on":
            return
        self.config_entry.async_create_task(
            self.hass, self.async_flush(), f"{self.name} flush"
        )

    async def async_flush(self) -> None:
        """Send the held alerts if the quiet hours are over.

        An alert of an outage that has already ended is dropped.
        """
        async with self._lock:
            if self._closed or not self._held:
                return
            now = dt_util.utcnow()
            if quiet_state(self.hass, self.notify, now).quiet:
                self._arm_flush(now)
                return
            items = [i for i in self._held.values() if not has_ended(i, now)]
            self._held = {}
            await self._async_save()
        if self.notify.targets:
            await self._async_send(items)

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
        problems = [r.problem_since for r in self.regions if r.problem_since]
        # The card shows the feed problem one hour after it starts.
        extra = (
            [min(problems) + timedelta(seconds=PROBLEM_AFTER_SECONDS)]
            if problems
            else []
        )
        when = next_boundary(planned, now, self.reminder, extra)
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
        if self._unsub_flush is not None:
            self._unsub_flush()
            self._unsub_flush = None
        if self._unsub_quiet_entity is not None:
            self._unsub_quiet_entity()
            self._unsub_quiet_entity = None
        for unsub in self._unsub_regions:
            unsub()
        self._unsub_regions = []
