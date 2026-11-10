"""Tests of the built-in notifications (2.3.0)."""

from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
import voluptuous_serialize
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER, ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from test_blueprint import ENGLISH, SLOVENIAN

from custom_components.elektro_celje.alerts import AlertEvent, OutageRecord
from custom_components.elektro_celje.const import (
    CONF_NOTIFY_TARGETS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_FROM,
    CONF_QUIET_HOURS,
    CONF_QUIET_TO,
    CONF_REGION,
    CONF_REMINDER_TIME,
    CONF_STATION,
    DOMAIN,
    EVENT_OUTAGE_DETECTED,
    EVENT_OUTAGE_REMOVED,
    FEED_URL,
    REGIONS,
    SECTION_ADVANCED,
    TZ,
)
from custom_components.elektro_celje.location import switch_unique_id
from custom_components.elektro_celje.models import ParseStatus
from custom_components.elektro_celje.notifications import (
    build_texts,
    make_item,
    merge,
    mobile_app_targets,
    quiet_window_end,
    tag,
)

FIXTURES = Path(__file__).parent / "fixtures"
VELENJE = FEED_URL.format(region="velenje")
EMPTY_FEED = "<rss version='2.0'><channel><title>t</title></channel></rss>"
USER_INPUT = {"name": "Home", CONF_REGION: "velenje", CONF_STATION: "Zabukovica Papež"}


def _feed(region: str) -> str:
    return (FIXTURES / f"rss_{region}_2026-11-09.xml").read_text(encoding="utf-8")


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


@pytest.fixture
async def ljubljana(hass: HomeAssistant) -> None:
    """Use the local time zone of the users."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")


@pytest.fixture
def phones(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    """Two phones: notify.mobile_app_pixel and notify.mobile_app_iphone."""
    return {
        name: async_mock_service(hass, "notify", name)
        for name in ("mobile_app_pixel", "mobile_app_iphone")
    }


def _entry(options: dict | None = None, station: str = "zabukovica papež"):
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={"name": "Home", CONF_REGION: "velenje", CONF_STATION: station},
        options=options or {},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _move(hass: HomeAssistant, freezer, moment: datetime) -> None:
    freezer.move_to(moment)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _sent(calls: list[ServiceCall]) -> list[tuple[str, str]]:
    return [(c.data["title"], c.data["message"]) for c in calls]


ON_PIXEL = {CONF_NOTIFY_TARGETS: ["mobile_app_pixel"]}


# --- Texts ------------------------------------------------------------------


@pytest.mark.parametrize(("event", "data", "title", "message"), SLOVENIAN)
async def test_slovenian_texts_equal_blueprint(
    hass, ljubljana, event, data, title, message
) -> None:
    """The Python texts equal the pinned built-in texts of the blueprint."""
    assert build_texts(event, {"location": "TP lopata", **data}, "sl") == (
        title,
        message,
    )


@pytest.mark.parametrize(("event", "data", "title", "message"), ENGLISH)
async def test_english_texts_equal_blueprint(
    hass, ljubljana, event, data, title, message
) -> None:
    assert build_texts(event, {"location": "TP lopata", **data}, "en") == (
        title,
        message,
    )


async def test_feed_text_is_never_a_template(hass, ljubljana) -> None:
    """Feed text and the location name stay literal text."""
    data = {
        "location": "{{ 7*7 }}",
        "start": None,
        "end": None,
        "all_day": False,
        "duration_minutes": None,
        "text": "{% if 1 %}x{% endif %} {location}",
    }
    _, message = build_texts("detected", data, "en")
    assert message == "{{ 7*7 }}: time unknown. {% if 1 %}x{% endif %} {location}"


def test_tag_matches_blueprint() -> None:
    assert tag("e1", "43:1") == "elektro_celje_e1_43:1"


# --- Quiet window and merge rules ------------------------------------------


@pytest.mark.parametrize(
    ("now", "start", "end", "expected"),
    [
        # Overnight range 22:00-07:00.
        (_local(9, 23), time(22), time(7), _local(10, 7)),
        (_local(9, 3), time(22), time(7), _local(9, 7)),
        (_local(9, 7), time(22), time(7), None),
        (_local(9, 12), time(22), time(7), None),
        (_local(9, 22), time(22), time(7), _local(10, 7)),
        # Day range 13:00-15:00.
        (_local(9, 14), time(13), time(15), _local(9, 15)),
        (_local(9, 15), time(13), time(15), None),
        (_local(9, 12), time(13), time(15), None),
        # Start equal to end: never quiet.
        (_local(9, 22), time(22), time(22), None),
        (_local(9, 3), time(0), time(0), None),
    ],
)
async def test_quiet_window_end(hass, ljubljana, now, start, end, expected) -> None:
    assert quiet_window_end(now, start, end) == expected


def _p(**extra) -> dict:
    return {"key": "1:0", "start": "2026-11-10T08:00:00+01:00", **extra}


def test_merge_detected_then_removed_drops_both() -> None:
    assert merge(make_item("detected", _p()), make_item("removed", _p())) is None


def test_merge_detected_then_changed_is_detected_with_new_time() -> None:
    changed = _p(start="2026-11-11T09:00:00+01:00", old_start="x", old_end="y")
    out = merge(make_item("detected", _p()), make_item("changed", changed))
    assert out == make_item("detected", _p(start="2026-11-11T09:00:00+01:00"))


def test_merge_later_alert_replaces_held_one() -> None:
    held = make_item("reminder", _p())
    new = make_item("removed", _p())
    assert merge(held, new) == new
    assert merge(None, new) == new


def test_merge_changed_twice_keeps_first_old_time() -> None:
    first = make_item("changed", _p(start="b", old_start="a", old_end="a2"))
    second = make_item("changed", _p(start="c", old_start="b", old_end="b2"))
    out = merge(first, second)
    assert out["kind"] == "changed"
    assert out["payload"]["start"] == "c"
    assert (out["payload"]["old_start"], out["payload"]["old_end"]) == ("a", "a2")


# --- Phones and the add-location form ---------------------------------------


def _mock_feeds(aioclient_mock: AiohttpClientMocker) -> None:
    for region in REGIONS:
        aioclient_mock.get(FEED_URL.format(region=region), text=_feed(region))


def _field(result, name: str):
    for key, value in result["data_schema"].schema.items():
        if key == name:
            return key, value
    return None


async def test_phone_labels_use_device_name(hass, phones) -> None:
    async_mock_service(hass, "notify", "persistent_notification")
    MockConfigEntry(domain="mobile_app", data={"device_name": "Pixel"}).add_to_hass(
        hass
    )
    assert mobile_app_targets(hass) == {
        "mobile_app_iphone": "mobile_app_iphone",
        "mobile_app_pixel": "Pixel",
    }


async def test_add_form_default_is_all_phones(
    hass, aioclient_mock, phones, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    _mock_feeds(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    key, selector = _field(result, CONF_NOTIFY_TARGETS)
    assert key.description["suggested_value"] == [
        "mobile_app_iphone",
        "mobile_app_pixel",
    ]
    assert selector.config["multiple"] is True
    # The user keeps the default: both phones.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**USER_INPUT, CONF_NOTIFY_TARGETS: key.description["suggested_value"]},
    )
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**USER_INPUT, "name": "Home"}
    assert result["options"] == {
        CONF_NOTIFY_TARGETS: ["mobile_app_iphone", "mobile_app_pixel"]
    }
    await hass.async_block_till_done()
    # The first refresh sends the new outage to both phones.
    assert len(phones["mobile_app_pixel"]) == 1
    assert len(phones["mobile_app_iphone"]) == 1


async def test_add_form_empty_choice_turns_notifications_off(
    hass, aioclient_mock, phones, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    _mock_feeds(aioclient_mock)
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # A cleared field does not reach the flow at all.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["options"] == {CONF_NOTIFY_TARGETS: []}
    await hass.async_block_till_done()
    assert len(detected) == 1
    assert phones["mobile_app_pixel"] == []
    assert phones["mobile_app_iphone"] == []


async def test_add_form_without_phones_has_no_field(hass, aioclient_mock) -> None:
    _mock_feeds(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert _field(result, CONF_NOTIFY_TARGETS) is None


async def test_import_and_reconfigure_add_no_phones(
    hass, aioclient_mock, phones, freezer
) -> None:
    freezer.move_to(_local(9, 7, 40))
    _mock_feeds(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert dict(entry.options) == {}
    await hass.async_block_till_done()
    assert phones["mobile_app_pixel"] == []

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "reconfigure"
    assert _field(result, CONF_NOTIFY_TARGETS) is None
    await _unload(hass, entry)


async def test_existing_entry_without_option_is_off(
    hass, aioclient_mock, phones, freezer
) -> None:
    """An entry from 2.2 has no notify_targets: no notification, no prompt."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry({CONF_REMINDER_TIME: "18:00:00"})
    await _setup(hass, entry)
    assert len(detected) == 1
    assert phones["mobile_app_pixel"] == []
    assert phones["mobile_app_iphone"] == []
    await _unload(hass, entry)


# --- Options flow -----------------------------------------------------------


async def test_options_form_defaults_and_section(hass, phones) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if callable(getattr(k, "default", None))
    }
    assert defaults[CONF_REMINDER_TIME] == "18:00:00"
    assert defaults[CONF_QUIET_HOURS] is True
    assert defaults[CONF_QUIET_FROM] == "22:00:00"
    assert defaults[CONF_QUIET_TO] == "07:00:00"
    key, _ = _field(result, CONF_NOTIFY_TARGETS)
    assert key.description["suggested_value"] == []
    advanced = schema[next(k for k in schema if k == SECTION_ADVANCED)]
    assert isinstance(advanced, section)
    assert advanced.options["collapsed"] is True
    inner = {str(k): v for k, v in advanced.schema.schema.items()}
    assert inner[CONF_QUIET_ENTITY].config["domain"] == [
        "schedule",
        "input_boolean",
        "binary_sensor",
    ]
    # The frontend can serialize the form.
    serialized = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    assert any(f["name"] == SECTION_ADVANCED for f in serialized)

    # Submit the defaults: the phones stay off, the defaults are stored.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {SECTION_ADVANCED: {}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        CONF_NOTIFY_TARGETS: [],
        CONF_REMINDER_TIME: "18:00:00",
        CONF_QUIET_HOURS: True,
        CONF_QUIET_FROM: "22:00:00",
        CONF_QUIET_TO: "07:00:00",
    }


async def test_options_store_phones_and_quiet_entity(hass, phones) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NOTIFY_TARGETS: ["mobile_app_pixel"],
            CONF_QUIET_HOURS: True,
            CONF_QUIET_FROM: "23:00:00",
            CONF_QUIET_TO: "06:30:00",
            SECTION_ADVANCED: {CONF_QUIET_ENTITY: "schedule.night"},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == ["mobile_app_pixel"]
    assert entry.options[CONF_QUIET_ENTITY] == "schedule.night"
    assert entry.options[CONF_QUIET_FROM] == "23:00:00"

    # The form shows the stored values. Clearing the entity removes it.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    key, _ = _field(result, CONF_NOTIFY_TARGETS)
    assert key.description["suggested_value"] == ["mobile_app_pixel"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {SECTION_ADVANCED: {}}
    )
    assert CONF_QUIET_ENTITY not in entry.options
    assert entry.options[CONF_NOTIFY_TARGETS] == []


# --- Switches ---------------------------------------------------------------

SWITCHES = {
    "detected": "switch.home_notify_new_outage",
    "reminder": "switch.home_notify_reminder",
    "changed": "switch.home_notify_changed_outage",
    "removed": "switch.home_notify_removed_outage",
}


async def test_four_switches_default_on(hass, aioclient_mock, phones, freezer) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry(ON_PIXEL)
    await _setup(hass, entry)
    registry = er.async_get(hass)
    for kind, entity_id in SWITCHES.items():
        assert hass.states.get(entity_id).state == "on", entity_id
        reg = registry.async_get(entity_id)
        assert reg.unique_id == switch_unique_id(entry.entry_id, kind)
        assert reg.entity_category is EntityCategory.CONFIG
        assert reg.translation_key == f"notify_{kind}"
    await _unload(hass, entry)


async def test_switch_off_gates_notification_not_event(
    hass, aioclient_mock, phones, freezer
) -> None:
    """A switch that is off stops the phone, not the event."""
    freezer.move_to(_local(9, 7, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    removed = async_capture_events(hass, EVENT_OUTAGE_REMOVED)
    entry = _entry({**ON_PIXEL, CONF_QUIET_HOURS: False})
    await _setup(hass, entry)
    assert len(phones["mobile_app_pixel"]) == 1  # detected

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCHES["removed"]}, blocking=True
    )
    for _ in range(2):  # R21: the second empty read fires removed.
        aioclient_mock.clear_requests()
        aioclient_mock.get(VELENJE, text=EMPTY_FEED)
        await _move(hass, freezer, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    assert len(removed) == 1
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_switch_restores_off_before_first_refresh(
    hass, aioclient_mock, phones, freezer
) -> None:
    """After a restart, a switch that was off gates the first refresh too."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry(ON_PIXEL)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        switch_unique_id(entry.entry_id, "detected"),
        suggested_object_id="home_notify_new_outage",
        config_entry=entry,
    )
    mock_restore_cache(hass, [State(SWITCHES["detected"], "off")])
    await _setup(hass, entry)
    assert len(detected) == 1
    assert phones["mobile_app_pixel"] == []
    assert hass.states.get(SWITCHES["detected"]).state == "off"
    assert hass.states.get(SWITCHES["reminder"]).state == "on"
    await _unload(hass, entry)


# --- Sending ----------------------------------------------------------------


async def test_send_to_two_phones_one_fails(
    hass, aioclient_mock, freezer, ljubljana, caplog
) -> None:
    """A failing phone logs a warning. The other phone still gets the alert."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    good = async_mock_service(hass, "notify", "mobile_app_good")

    async def _fail(call: ServiceCall) -> None:
        raise HomeAssistantError("phone is gone")

    hass.services.async_register("notify", "mobile_app_bad", _fail)
    hass.config.language = "en"
    entry = _entry({CONF_NOTIFY_TARGETS: ["mobile_app_bad", "mobile_app_good"]})
    await _setup(hass, entry)

    assert len(good) == 1
    assert good[0].data == {
        "title": "Planned power outage",
        "message": "Home: 9 Nov 2026, 08:30–11:00 (2 h 30 min)",
        "data": {"tag": f"elektro_celje_{entry.entry_id}_43322:0"},
    }
    assert "notify.mobile_app_bad" in caplog.text
    assert "phone is gone" in caplog.text
    await _unload(hass, entry)


async def test_slovenian_language_of_home_assistant(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.config.language = "sl"
    entry = _entry(ON_PIXEL)
    await _setup(hass, entry)
    assert _sent(phones["mobile_app_pixel"]) == [
        ("Načrtovan izklop", "Home: 9. 11. 2026, 08:30–11:00 (2 h 30 min)")
    ]
    await _unload(hass, entry)


# --- Quiet hours ------------------------------------------------------------


async def test_quiet_hours_hold_then_flush_at_end(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """At 23:00 the alert waits. The event fires at once. 07:00 sends it."""
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    entry = _entry(ON_PIXEL)
    await _setup(hass, entry)
    assert len(detected) == 1
    assert phones["mobile_app_pixel"] == []

    await _move(hass, freezer, _local(9, 6, 59))
    assert phones["mobile_app_pixel"] == []
    await _move(hass, freezer, _local(9, 7, 0))
    assert len(phones["mobile_app_pixel"]) == 1
    assert phones["mobile_app_pixel"][0].data["title"] == "Planned power outage"
    await _unload(hass, entry)


async def test_outage_that_starts_before_quiet_end_is_sent_at_once(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """The outage starts at 08:30. Quiet hours end at 09:00. Send now."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry({**ON_PIXEL, CONF_QUIET_FROM: "07:00:00", CONF_QUIET_TO: "09:00"})
    await _setup(hass, entry)
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_held_alert_survives_reload(
    hass, aioclient_mock, phones, freezer, ljubljana, hass_storage
) -> None:
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry(ON_PIXEL)
    await _setup(hass, entry)
    await _unload(hass, entry)
    held = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["held"]
    assert list(held) == ["43322:0"]
    assert held["43322:0"]["kind"] == "detected"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert phones["mobile_app_pixel"] == []
    await _move(hass, freezer, _local(9, 7, 0))
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_options_change_flushes_held_alerts(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """Turning the quiet hours off sends the held alerts at once."""
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry(ON_PIXEL)
    await _setup(hass, entry)
    assert phones["mobile_app_pixel"] == []
    hass.config_entries.async_update_entry(
        entry, options={**ON_PIXEL, CONF_QUIET_HOURS: False}
    )
    await hass.async_block_till_done()
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_detected_then_removed_while_held_sends_nothing(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    removed = async_capture_events(hass, EVENT_OUTAGE_REMOVED)
    # The outage starts at 08:30, after the quiet end of 08:20.
    entry = _entry({**ON_PIXEL, CONF_QUIET_FROM: "07:00:00", CONF_QUIET_TO: "08:20"})
    coordinator = await _setup(hass, entry)
    assert list(coordinator._held) == ["43322:0"]
    for minute in (55, 70):  # 07:55 and 08:10, two empty reads.
        aioclient_mock.clear_requests()
        aioclient_mock.get(VELENJE, text=EMPTY_FEED)
        await _move(hass, freezer, _local(9, 7, 0) + timedelta(minutes=minute))
    assert len(removed) == 1
    assert coordinator._held == {}
    await _move(hass, freezer, _local(9, 8, 20))
    assert phones["mobile_app_pixel"] == []
    await _unload(hass, entry)


def _record(key: str, start: datetime) -> OutageRecord:
    return OutageRecord(
        key=key,
        notice_id=key.split(":")[0],
        region="velenje",
        station_text="TP x",
        text="t",
        link="https://example.test",
        status=ParseStatus.OK,
        start=start,
        end=start + timedelta(hours=2),
        all_day=False,
        first_seen=start,
        reminder_sent=False,
    )


async def test_route_changed_after_detected_sends_detected_with_new_time(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=EMPTY_FEED)
    entry = _entry(ON_PIXEL)
    coordinator = await _setup(hass, entry)
    now = dt_util.utcnow()
    first = _record("9:0", _local(10, 9))
    later = _record("9:0", _local(11, 10))
    assert coordinator._route([AlertEvent("detected", first)], now) == []
    assert (
        coordinator._route([AlertEvent("changed", later, first.start, first.end)], now)
        == []
    )
    held = coordinator._held["9:0"]
    assert held["kind"] == "detected"
    assert held["payload"]["start"] == _local(11, 10).isoformat()
    assert "old_start" not in held["payload"]
    # A reminder that is off keeps the held alert.
    coordinator.notify_enabled["reminder"] = False
    assert coordinator._route([AlertEvent("reminder", later)], now) == []
    assert coordinator._held["9:0"]["kind"] == "detected"
    # A reminder that is on replaces the held alert.
    coordinator.notify_enabled["reminder"] = True
    assert coordinator._route([AlertEvent("reminder", later)], now) == []
    assert coordinator._held["9:0"]["kind"] == "reminder"
    await _unload(hass, entry)


async def test_quiet_entity_holds_until_off(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """With an entity, the alert waits while it is on and flushes on off."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.states.async_set("input_boolean.quiet", "on")
    detected = async_capture_events(hass, EVENT_OUTAGE_DETECTED)
    # The entity replaces the times: 07:40 is not in 22:00-07:00.
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "input_boolean.quiet"})
    await _setup(hass, entry)
    assert len(detected) == 1
    assert phones["mobile_app_pixel"] == []

    hass.states.async_set("input_boolean.quiet", "off")
    await hass.async_block_till_done()
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_quiet_entity_off_at_startup_flushes(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.states.async_set("input_boolean.quiet", "on")
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "input_boolean.quiet"})
    await _setup(hass, entry)
    await _unload(hass, entry)
    assert phones["mobile_app_pixel"] == []

    hass.states.async_set("input_boolean.quiet", "off")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_schedule_end_lets_an_early_outage_through(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """A schedule tells its end. An outage that starts before it is sent now."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.states.async_set(
        "schedule.night", "on", {"next_event": _local(9, 9).isoformat()}
    )
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "schedule.night"})
    await _setup(hass, entry)
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_ended_outage_is_skipped_on_flush(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.states.async_set("input_boolean.quiet", "on")
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "input_boolean.quiet"})
    coordinator = await _setup(hass, entry)
    assert list(coordinator._held) == ["43322:0"]

    await _move(hass, freezer, _local(9, 11, 30))  # The outage ended at 11:00.
    hass.states.async_set("input_boolean.quiet", "off")
    await hass.async_block_till_done()
    assert coordinator._held == {}
    assert phones["mobile_app_pixel"] == []
    await _unload(hass, entry)


async def test_equal_from_and_to_is_never_quiet(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry({**ON_PIXEL, CONF_QUIET_FROM: "22:00:00", CONF_QUIET_TO: "22:00"})
    await _setup(hass, entry)
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_unload_cancels_flush_timer_and_listener(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(8, 23, 0))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry(ON_PIXEL)
    coordinator = await _setup(hass, entry)
    assert coordinator._unsub_flush is not None
    await _unload(hass, entry)
    assert coordinator._unsub_flush is None
    await _move(hass, freezer, _local(9, 7, 0))
    assert phones["mobile_app_pixel"] == []


async def test_diagnostics_redact_phones_and_quiet_entity(
    hass, aioclient_mock, phones, freezer
) -> None:
    from custom_components.elektro_celje.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "schedule.night"})
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["options"][CONF_NOTIFY_TARGETS] == "**REDACTED**"
    assert diag["entry"]["options"][CONF_QUIET_ENTITY] == "**REDACTED**"
    await _unload(hass, entry)


async def test_quiet_window_end_on_autumn_dst_day(hass, ljubljana) -> None:
    """25 Oct 2026: 02:00-03:00 occurs twice. The end is after now."""
    utc = dt_util.UTC
    # 02:30 CET, the second pass (00:30 UTC was the first pass, CEST).
    second_pass = datetime(2026, 10, 25, 1, 30, tzinfo=utc)
    end = quiet_window_end(second_pass, time(1), time(2, 45))
    assert end == datetime(2026, 10, 25, 1, 45, tzinfo=utc)  # 02:45 CET
    assert end > second_pass
    # 02:30 CEST, the first pass: the first 02:45 is the end.
    first_pass = datetime(2026, 10, 25, 0, 30, tzinfo=utc)
    assert quiet_window_end(first_pass, time(1), time(2, 45)) == datetime(
        2026, 10, 25, 0, 45, tzinfo=utc
    )


async def test_quiet_window_end_on_spring_dst_day(hass, ljubljana) -> None:
    """29 Mar 2026: 02:00-03:00 does not exist. The end is still after now."""
    utc = dt_util.UTC
    now = datetime(2026, 3, 29, 0, 45, tzinfo=utc)  # 01:45 CET
    end = quiet_window_end(now, time(1), time(2, 30))
    assert end is not None
    assert end > now
    assert end <= datetime(2026, 3, 29, 1, 30, tzinfo=utc)  # 03:30 CEST


async def test_flush_timer_on_autumn_dst_day_does_not_loop(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """A held alert at 02:30 CET (second pass) waits for 02:45 CET."""
    freezer.move_to(datetime(2026, 10, 25, 1, 30, tzinfo=dt_util.UTC))
    aioclient_mock.get(VELENJE, text=EMPTY_FEED)
    entry = _entry({**ON_PIXEL, CONF_QUIET_FROM: "01:00:00", CONF_QUIET_TO: "02:45"})
    coordinator = await _setup(hass, entry)
    coordinator._held["9:0"] = make_item(
        "detected",
        {"key": "9:0", "start": "2026-10-26T09:00:00+01:00", "location": "Home"},
    )
    coordinator._arm_flush(dt_util.utcnow())
    await hass.async_block_till_done()
    assert phones["mobile_app_pixel"] == []
    assert coordinator._held
    await _move(hass, freezer, datetime(2026, 10, 25, 1, 45, tzinfo=dt_util.UTC))
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_quiet_entity_missing_at_setup_holds(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """A quiet entity that does not exist yet keeps the alert waiting."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "schedule.night"})
    coordinator = await _setup(hass, entry)
    assert list(coordinator._held) == ["43322:0"]
    assert phones["mobile_app_pixel"] == []
    # The entity appears with a real "off" state: flush.
    hass.states.async_set("schedule.night", "off")
    await hass.async_block_till_done()
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_quiet_entity_unavailable_blip_does_not_flush(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    hass.states.async_set("binary_sensor.night", "on")
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "binary_sensor.night"})
    coordinator = await _setup(hass, entry)
    for state in ("unavailable", "unknown", "on"):
        hass.states.async_set("binary_sensor.night", state)
        await hass.async_block_till_done()
    assert list(coordinator._held) == ["43322:0"]
    assert phones["mobile_app_pixel"] == []
    await _unload(hass, entry)


async def test_quiet_entity_still_unknown_after_grace_flushes(
    hass, aioclient_mock, phones, freezer, ljubljana
) -> None:
    """After 10 minutes, a missing entity counts as not quiet."""
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    entry = _entry({**ON_PIXEL, CONF_QUIET_ENTITY: "input_boolean.gone"})
    await _setup(hass, entry)
    await _move(hass, freezer, _local(9, 7, 49))
    assert phones["mobile_app_pixel"] == []
    await _move(
        hass,
        freezer,
        _local(
            9,
            7,
            50,
        )
        + timedelta(seconds=1),
    )
    assert len(phones["mobile_app_pixel"]) == 1
    await _unload(hass, entry)


async def test_each_failing_phone_logs_a_warning(
    hass, aioclient_mock, freezer, ljubljana, caplog
) -> None:
    freezer.move_to(_local(9, 7, 40))
    aioclient_mock.get(VELENJE, text=_feed("velenje"))
    good = async_mock_service(hass, "notify", "mobile_app_good")

    async def _fail(call: ServiceCall) -> None:
        raise HomeAssistantError(f"{call.service} is gone")

    for name in ("mobile_app_a", "mobile_app_b"):
        hass.services.async_register("notify", name, _fail)
    targets = ["mobile_app_a", "mobile_app_good", "mobile_app_b"]
    entry = _entry({CONF_NOTIFY_TARGETS: targets})
    await _setup(hass, entry)
    assert len(good) == 1
    assert "notify.mobile_app_a: mobile_app_a is gone" in caplog.text
    assert "notify.mobile_app_b: mobile_app_b is gone" in caplog.text
    await _unload(hass, entry)
