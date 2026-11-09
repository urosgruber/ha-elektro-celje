"""Tests for the sensors, the binary sensors and the calendar."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.elektro_celje.const import (
    CONF_REGION,
    CONF_STATION,
    DOMAIN,
    FEED_URL,
    TZ,
)

FIXTURES = Path(__file__).parent / "fixtures"
VELENJE = FEED_URL.format(region="velenje")


def _feed(region: str) -> str:
    return (FIXTURES / f"rss_{region}_2026-11-09.xml").read_text(encoding="utf-8")


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def _entry(station: str = "zabukovica papež") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={"name": "Home", CONF_REGION: "velenje", CONF_STATION: station},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _entity_id(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None
    return entity_id


def _state(hass: HomeAssistant, entry, platform: str, key: str):
    return hass.states.get(_entity_id(hass, entry, platform, key))


async def test_entities_for_planned_outage(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    planned = _state(hass, entry, "sensor", "planned_outages")
    assert planned.state == "1"
    outages = planned.attributes["outages"]
    assert len(outages) == 1
    assert outages[0]["start"] == _local(9, 8, 30).isoformat()
    assert outages[0]["end"] == _local(9, 11).isoformat()
    assert outages[0]["status"] == "ok"
    assert outages[0]["all_day"] is False
    assert len(outages[0]["text"]) <= 300
    assert planned.attributes["feed_urls"] == [VELENJE]
    assert _state(hass, entry, "sensor", "days_until_outage").state == "0"
    start = _state(hass, entry, "sensor", "next_outage_start").state
    assert datetime.fromisoformat(start) == _local(9, 8, 30)
    end = _state(hass, entry, "sensor", "next_outage_end").state
    assert datetime.fromisoformat(end) == _local(9, 11)
    assert _state(hass, entry, "sensor", "last_checked").state != "unknown"
    assert _state(hass, entry, "sensor", "last_successful_check").state != "unknown"
    assert _state(hass, entry, "binary_sensor", "outage_planned").state == "on"
    assert _state(hass, entry, "binary_sensor", "outage_now").state == "off"
    assert _state(hass, entry, "binary_sensor", "feed_problem").state == "off"

    device = er.async_get(hass).async_get(
        _entity_id(hass, entry, "sensor", "planned_outages")
    )
    assert device.device_id is not None


async def test_outage_now_turns_on(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    freezer.move_to(_local(9, 8, 31))
    async_fire_time_changed(hass, _local(9, 8, 31))
    await hass.async_block_till_done()
    assert _state(hass, entry, "binary_sensor", "outage_now").state == "on"


async def test_nothing_planned_states(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry("no such station")
    await _setup(hass, entry)

    assert _state(hass, entry, "sensor", "planned_outages").state == "0"
    assert _state(hass, entry, "sensor", "days_until_outage").state == "unknown"
    assert _state(hass, entry, "sensor", "next_outage_start").state == "unknown"
    assert _state(hass, entry, "sensor", "next_outage_end").state == "unknown"
    assert _state(hass, entry, "binary_sensor", "outage_planned").state == "off"
    assert _state(hass, entry, "binary_sensor", "outage_now").state == "off"


async def test_feed_problem_entity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(VELENJE, status=500)
    region = entry.runtime_data.regions[0]
    await region.async_refresh()
    await hass.async_block_till_done()

    problem = _state(hass, entry, "binary_sensor", "feed_problem")
    assert problem.state == "on"
    assert problem.attributes["problem_since"] is not None
    planned = _state(hass, entry, "sensor", "planned_outages")
    assert planned.state == "1"
    assert len(planned.attributes["outages"]) == 1
    assert _state(hass, entry, "binary_sensor", "outage_planned").state == "on"


async def test_entities_stay_available_when_update_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    coordinator = entry.runtime_data
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert _state(hass, entry, "sensor", "planned_outages").state == "1"
    assert _state(hass, entry, "binary_sensor", "feed_problem").state != "unavailable"


async def test_calendar_events_in_range(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    entity_id = _entity_id(hass, entry, "calendar", "planned_outages")

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": _local(9, 0).isoformat(),
            "end_date_time": _local(10, 0).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    events = result[entity_id]["events"]
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]["start"]) == _local(9, 8, 30)
    assert datetime.fromisoformat(events[0]["end"]) == _local(9, 11)
    assert events[0]["summary"].startswith("Izklop elektrike: ")
    assert "Zabukovica" in events[0]["summary"]
    assert "http" in events[0]["description"]

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": _local(10, 0).isoformat(),
            "end_date_time": _local(11, 0).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    assert result[entity_id]["events"] == []
    assert hass.states.get(entity_id).attributes["message"].startswith("Izklop")


async def test_failed_notice_in_attribute_not_calendar(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    from custom_components.elektro_celje.calendar import _event
    from custom_components.elektro_celje.models import Outage, ParseStatus

    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    failed = Outage(
        key="9:0",
        notice_id="9",
        region="velenje",
        station_text="Zabukovica Papež",
        text="x" * 500,
        link="https://example.com",
        status=ParseStatus.FAILED,
        start=None,
        end=None,
        all_day=False,
    )
    assert _event(failed) is None
    coordinator = entry.runtime_data
    coordinator.data.planned.append(failed)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = _state(hass, entry, "sensor", "planned_outages")
    assert state.state == "2"
    last = state.attributes["outages"][-1]
    assert last["status"] == "failed"
    assert last["start"] is None
    assert len(last["text"]) == 300
    assert _state(hass, entry, "binary_sensor", "outage_planned").state == "on"
    assert _state(hass, entry, "sensor", "days_until_outage").state == "0"
    entity_id = _entity_id(hass, entry, "calendar", "planned_outages")
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": _local(1, 0).isoformat(),
            "end_date_time": _local(30, 0).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    assert len(result[entity_id]["events"]) == 1


async def test_date_only_is_all_day_event() -> None:
    from custom_components.elektro_celje.calendar import _event
    from custom_components.elektro_celje.models import Outage, ParseStatus

    outage = Outage(
        key="1:0",
        notice_id="1",
        region="celje",
        station_text="Test",
        text="t",
        link="",
        status=ParseStatus.DATE_ONLY,
        start=_local(10, 0),
        end=_local(11, 0),
        all_day=True,
    )
    event = _event(outage)
    assert event.start.isoformat() == "2026-11-10"
    assert event.end.isoformat() == "2026-11-11"
    assert not isinstance(event.start, datetime)


async def test_outages_attribute_not_recorded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    from homeassistant.helpers import entity_platform  # noqa: F401

    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    from custom_components.elektro_celje.binary_sensor import OutagePlannedSensor
    from custom_components.elektro_celje.sensor import ElektroCeljeSensor

    for cls in (ElektroCeljeSensor, OutagePlannedSensor):
        assert {"outages", "feed_urls"} <= cls._unrecorded_attributes


async def test_forward_failure_releases_regions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=RuntimeError("boom"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.data[DOMAIN]["regions"] == {}
    assert entry.runtime_data._shutdown_requested


async def test_calendar_keeps_ended_outage(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """An ended outage that the feed still lists stays in the calendar."""
    freezer.move_to(_local(9, 23))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    entity_id = _entity_id(hass, entry, "calendar", "planned_outages")

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": _local(9, 0).isoformat(),
            "end_date_time": _local(10, 0).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    events = result[entity_id]["events"]
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]["start"]) == _local(9, 8, 30)
    assert datetime.fromisoformat(events[0]["end"]) == _local(9, 11)
    assert _state(hass, entry, "binary_sensor", "outage_planned").state == "off"
    assert _state(hass, entry, "sensor", "planned_outages").state == "0"


async def test_ended_today_attribute(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """The ended_today attribute lists the outages that ended today."""
    freezer.move_to(_local(9, 23))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)

    state = _state(hass, entry, "sensor", "planned_outages")
    assert state.attributes["outages"] == []
    ended = state.attributes["ended_today"]
    assert len(ended) == 1
    assert ended[0]["start"] == _local(9, 8, 30).isoformat()
    assert ended[0]["end"] == _local(9, 11).isoformat()
    assert ended[0]["status"] == "ok"


async def test_ended_today_empty_before_end(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """An outage that has not ended is planned, not ended today."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    state = _state(hass, entry, "sensor", "planned_outages")
    assert state.attributes["ended_today"] == []


async def test_ended_today_clears_at_midnight(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """After local midnight the ended_today attribute is empty."""
    freezer.move_to(_local(9, 23))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    state = _state(hass, entry, "sensor", "planned_outages")
    assert len(state.attributes["ended_today"]) == 1

    freezer.move_to(_local(10, 0, 1))
    async_fire_time_changed(hass, _local(10, 0, 1))
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", "planned_outages")
    assert state.attributes["ended_today"] == []


async def test_device_info_model(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """The device names the data source and the kind of data."""
    from homeassistant.helpers import device_registry as dr

    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry()
    await _setup(hass, entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.manufacturer == "Elektro Celje"
    assert device.model == "Planned outage notices (RSS)"
