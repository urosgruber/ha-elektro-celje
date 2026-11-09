"""Tests for the location coordinator and the integration setup."""

import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.elektro_celje.const import (
    CONF_REGION,
    CONF_REMINDER_TIME,
    CONF_STATION,
    DOMAIN,
    EVENT_OUTAGE_DETECTED,
    EVENT_OUTAGE_REMINDER,
    EVENT_OUTAGE_REMOVED,
    FEED_URL,
    REGIONS,
    TZ,
)
from custom_components.elektro_celje.location import (
    LocationCoordinator,
    async_clear_alert_state,
)
from custom_components.elektro_celje.outages import is_active

FIXTURES = Path(__file__).parent / "fixtures"
VELENJE = FEED_URL.format(region="velenje")


def _feed(region: str) -> str:
    return (FIXTURES / f"rss_{region}_2026-11-09.xml").read_text(encoding="utf-8")


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def _entry(
    name: str = "Home",
    region: str = "velenje",
    station: str = "zabukovica papež",
    options: dict | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        data={"name": name, CONF_REGION: region, CONF_STATION: station},
        options=options or {},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> LocationCoordinator:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_zabukovica_detects_outage(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry()
    coordinator = await _setup(hass, entry)

    assert len(detected) == 1
    data = detected[0].data
    assert data["entry_id"] == entry.entry_id
    assert data["location"] == "Home"
    assert data["notice_id"] == "43322"
    assert data["start"] == _local(9, 8, 30).isoformat()
    assert data["end"] == _local(9, 11).isoformat()

    location = coordinator.data
    assert len(location.planned) == 1
    assert location.planned[0].start == _local(9, 8, 30)
    assert location.feed_ok
    assert location.feed_urls == [VELENJE]
    assert location.last_success is not None
    assert location.last_attempt is not None
    assert location.problem_since is None
    await _unload(hass, entry)


async def test_all_regions_location_uses_four_feeds(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    for region in REGIONS:
        aioclient_mock.get(FEED_URL.format(region=region), text=_feed(region))
    entry = _entry(region="all", station="spodnji žusem")
    coordinator = await _setup(hass, entry)

    assert aioclient_mock.call_count == 4
    location = coordinator.data
    assert sorted(location.feed_urls) == sorted(
        FEED_URL.format(region=r) for r in REGIONS
    )
    assert location.feed_ok
    assert [o.notice_id for o in location.planned] == ["43316", "43332"]
    await _unload(hass, entry)


async def test_one_failed_feed_of_four_is_a_problem(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    for region in REGIONS:
        url = FEED_URL.format(region=region)
        if region == "krsko":
            aioclient_mock.get(url, status=500)
        else:
            aioclient_mock.get(url, text=_feed(region))
    entry = _entry(region="all", station="spodnji žusem")
    coordinator = await _setup(hass, entry)

    location = coordinator.data
    assert not location.feed_ok
    assert location.last_success is None
    assert location.problem_since is not None
    assert len(location.planned) == 2
    await _unload(hass, entry)


async def test_two_locations_same_notice_fire_separately(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    first = _entry(name="Home")
    second = _entry(name="Office")
    await _setup(hass, first)
    await _setup(hass, second)

    assert aioclient_mock.call_count == 1
    assert sorted((e.data["entry_id"], e.data["location"]) for e in detected) == (
        sorted([(first.entry_id, "Home"), (second.entry_id, "Office")])
    )
    await _unload(hass, first)
    await _unload(hass, second)


async def test_outage_now_flips_at_start_without_poll(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 8, 29))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    coordinator = await _setup(hass, entry)
    before = coordinator.data
    assert not is_active(before.planned[0], dt_util.utcnow())

    updates: list[None] = []
    unsub = coordinator.async_add_listener(lambda: updates.append(None))
    freezer.move_to(_local(9, 8, 30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 1
    assert updates
    assert coordinator.data is not before
    assert is_active(coordinator.data.planned[0], dt_util.utcnow())
    unsub()
    await _unload(hass, entry)


async def test_reminder_event_at_18(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 17, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    reminders = async_capture_events(hass, EVENT_OUTAGE_REMINDER)
    entry = _entry(station="dobriša vas")
    await _setup(hass, entry)
    assert reminders == []

    freezer.move_to(_local(9, 18, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(reminders) == 1
    assert reminders[0].data["notice_id"] == "43326"
    await _unload(hass, entry)


async def test_reminder_time_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 17, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    reminders = async_capture_events(hass, EVENT_OUTAGE_REMINDER)
    entry = _entry(station="dobriša vas", options={CONF_REMINDER_TIME: "20:30:00"})
    await _setup(hass, entry)

    freezer.move_to(_local(9, 18, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert reminders == []

    freezer.move_to(_local(9, 20, 30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(reminders) == 1
    await _unload(hass, entry)


async def test_restart_does_not_refire(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry()
    await _setup(hass, entry)
    assert len(detected) == 1
    await _unload(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(detected) == 1
    await _unload(hass, entry)


async def test_restart_with_feed_down_keeps_outages(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    removed = async_capture_events(hass, EVENT_OUTAGE_REMOVED)
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry()
    coordinator = await _setup(hass, entry)
    planned = coordinator.data.planned
    await _unload(hass, entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(VELENJE, status=500)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    location = entry.runtime_data.data
    assert location.planned == planned
    assert not location.feed_ok
    assert location.problem_since is not None
    assert removed == []
    assert len(detected) == 1
    await _unload(hass, entry)


async def test_setup_with_feed_down_and_no_store(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, status=500)
    entry = _entry()
    coordinator = await _setup(hass, entry)

    location = coordinator.data
    assert not location.feed_ok
    assert location.planned == []
    assert location.outages == []
    assert location.last_success is None
    await _unload(hass, entry)


async def test_records_saved_before_events(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer, hass_storage
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    entry.add_to_hass(hass)
    key = f"{DOMAIN}.{entry.entry_id}"
    stored_at_event: list[object] = []

    @callback
    def _on_detected(_event: Event) -> None:
        # A callback runs at the moment the event fires.
        stored_at_event.append(hass_storage.get(key))

    hass.bus.async_listen(EVENT_OUTAGE_DETECTED, _on_detected)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(stored_at_event) == 1
    stored = stored_at_event[0]
    assert stored is not None
    assert [r["notice_id"] for r in stored["data"]["records"]] == ["43322"]
    await _unload(hass, entry)


async def test_clear_alert_state_removes_store(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer, hass_storage
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry()
    await _setup(hass, entry)
    await _unload(hass, entry)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage

    await async_clear_alert_state(hass, entry.entry_id)
    assert key not in hass_storage

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(detected) == 2
    await _unload(hass, entry)


async def test_remove_entry_removes_store(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer, hass_storage
) -> None:
    """Removing a location deletes its alert Store (I4)."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
    assert hass.data[DOMAIN]["regions"] == {}


async def test_feed_recovery_refreshes_location(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, status=500)
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry()
    coordinator = await _setup(hass, entry)
    assert not coordinator.data.feed_ok

    aioclient_mock.clear_requests()
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    freezer.tick(timedelta(minutes=15, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert coordinator.data.feed_ok
    assert len(coordinator.data.planned) == 1
    assert len(detected) == 1
    await _unload(hass, entry)


async def test_unload_releases_regions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    for region in REGIONS:
        aioclient_mock.get(FEED_URL.format(region=region), text=_feed(region))
    entry = _entry(region="all")
    await _setup(hass, entry)
    assert set(hass.data[DOMAIN]["regions"]) == set(REGIONS)

    await _unload(hass, entry)
    assert hass.data[DOMAIN]["regions"] == {}
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_change_reloads_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    first = await _setup(hass, entry)
    assert first.reminder == time(18, 0)

    hass.config_entries.async_update_entry(
        entry, options={CONF_REMINDER_TIME: "19:15:00"}
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not first
    assert entry.runtime_data.reminder == time(19, 15)
    await _unload(hass, entry)


async def test_failed_evaluation_still_arms_boundary_timer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    coordinator = await _setup(hass, _entry())
    assert coordinator._unsub_timer is not None
    coordinator._unsub_timer()
    coordinator._unsub_timer = None

    with patch(
        "custom_components.elektro_celje.location.evaluate",
        side_effect=RuntimeError("boom"),
    ):
        await coordinator.async_refresh()

    assert coordinator._unsub_timer is not None


async def test_no_save_or_event_after_shutdown(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    coordinator = await _setup(hass, _entry())
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    coordinator._records.clear()

    await coordinator.async_shutdown()
    with patch.object(coordinator._store, "async_save") as save:
        await coordinator._async_update_data()

    save.assert_not_called()
    assert detected == []
    assert coordinator._unsub_timer is None


async def test_shutdown_waits_for_refresh_in_flight(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    coordinator = await _setup(hass, _entry())
    await coordinator._lock.acquire()
    shutdown = hass.async_create_task(coordinator.async_shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    coordinator._lock.release()
    await shutdown
