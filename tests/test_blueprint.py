"""Tests of the notification blueprint."""

from pathlib import Path

from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml

PATH = Path("blueprints/automation/elektro_celje/outage_notify.yaml")
EVENTS = {
    "elektro_celje_outage_detected",
    "elektro_celje_outage_reminder",
    "elektro_celje_outage_changed",
    "elektro_celje_outage_removed",
}


def _data() -> dict:
    return load_yaml(str(PATH))


def test_blueprint_is_valid() -> None:
    """The blueprint passes the HA blueprint schema."""
    blueprint = Blueprint(
        _data(), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.domain == "automation"


def test_blueprint_inputs() -> None:
    """The blueprint has the notify device, four booleans and the location filter."""
    blueprint = Blueprint(
        _data(), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert set(blueprint.inputs) == {
        "notify_device",
        "on_detected",
        "on_reminder",
        "on_changed",
        "on_removed",
        "locations",
    }


def test_blueprint_triggers() -> None:
    """The blueprint listens to the four events."""
    triggers = _data()["triggers"]
    assert {t["event_type"] for t in triggers} == EVENTS
    assert all(t["trigger"] == "event" for t in triggers)


def test_boolean_defaults() -> None:
    """All four booleans default to true."""
    inputs = _data()["blueprint"]["input"]
    for key in ("on_detected", "on_reminder", "on_changed", "on_removed"):
        assert inputs[key]["default"] is True


def _variables(hass, data: dict) -> dict:
    """Render the action variables of the blueprint for one event."""
    spec = _data()["actions"][0]["variables"]
    out: dict = {"d": data}
    for key in ("titles", "when", "old_when", "duration", "message"):
        value = spec[key]
        out[key] = (
            value
            if isinstance(value, dict)
            else Template(value, hass).async_render(out, parse_result=False).strip()
        )
    return out


async def test_message_with_time(hass) -> None:
    """The message has the location, the date, the time and the duration."""
    data = {
        "location": "Dom",
        "start": "2026-11-10T08:30:00+01:00",
        "end": "2026-11-10T11:00:00+01:00",
        "all_day": False,
        "duration_minutes": 150,
        "text": "x",
    }
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    message = _variables(hass, data)["message"]
    assert "Dom" in message
    assert "10. 11. 2026" in message
    assert "08:30–11:00" in message
    assert "2 h 30 min" in message


async def test_message_of_failed_notice(hass) -> None:
    """A failed notice says that the time is unknown and adds the text."""
    data = {
        "location": "Dom",
        "start": None,
        "end": None,
        "all_day": False,
        "duration_minutes": None,
        "text": "Izklop na Lopati",
    }
    message = _variables(hass, data)["message"]
    assert "čas ni znan" in message
    assert "Izklop na Lopati" in message


def _render(hass, template: str, variables: dict) -> str:
    return Template(template, hass).async_render(variables, parse_result=False)


def _tag_template() -> str:
    return _data()["actions"][1]["data"]["tag"]


async def test_tag_differs_for_two_intervals_of_one_notice(hass) -> None:
    """Two outages of one notice get two tags, so both notifications stay."""
    template = _tag_template()
    tags = {
        _render(
            hass,
            template,
            {"trigger": {"event": {"data": {"entry_id": "e1", "notice_id": "43",
                                            "key": key}}}},
        )
        for key in ("43:0", "43:1")
    }  # fmt: skip
    assert tags == {"elektro_celje_e1_43:0", "elektro_celje_e1_43:1"}


async def test_tag_of_changed_equals_tag_of_detected(hass) -> None:
    """A change of one outage replaces its earlier notification."""
    template = _tag_template()
    data = {"entry_id": "e1", "notice_id": "43", "key": "43:1"}
    detected = _render(hass, template, {"trigger": {"event": {"data": data}}})
    changed = _render(
        hass,
        template,
        {"trigger": {"event": {"data": {**data, "old_start": "x", "old_end": "y"}}}},
    )
    assert detected == changed == "elektro_celje_e1_43:1"


async def test_changed_message_shows_old_and_new_time(hass) -> None:
    """The changed message says "was <old time>, now <new time>"."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    data = {
        "location": "Dom",
        "start": "2026-11-11T09:00:00+01:00",
        "end": "2026-11-11T12:00:00+01:00",
        "old_start": "2026-11-10T08:30:00+01:00",
        "old_end": "2026-11-10T11:00:00+01:00",
        "all_day": False,
        "duration_minutes": 180,
        "text": "x",
    }
    message = _variables(hass, data)["message"]
    assert "Dom" in message
    assert "prej 10. 11. 2026, 08:30–11:00" in message
    assert "zdaj 11. 11. 2026, 09:00–12:00" in message
    assert message.index("prej") < message.index("zdaj")


async def test_message_without_old_time_has_no_was_part(hass) -> None:
    """A detected event has no old time, so the message has no "prej" part."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    data = {
        "location": "Dom",
        "start": "2026-11-11T09:00:00+01:00",
        "end": "2026-11-11T12:00:00+01:00",
        "all_day": False,
        "duration_minutes": 180,
        "text": "x",
    }
    message = _variables(hass, data)["message"]
    assert "prej" not in message
    assert "zdaj" not in message


async def test_changed_message_with_old_all_day_and_unknown(hass) -> None:
    """An old all-day time says "ves dan"; an old unknown time says so."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    base = {
        "location": "Dom",
        "start": "2026-11-11T09:00:00+01:00",
        "end": "2026-11-11T12:00:00+01:00",
        "all_day": False,
        "duration_minutes": 180,
        "text": "x",
    }
    all_day = {
        **base,
        "old_start": "2026-11-10T00:00:00+01:00",
        "old_end": "2026-11-11T00:00:00+01:00",
    }
    assert "prej 10. 11. 2026, ves dan, zdaj" in _variables(hass, all_day)["message"]
    unknown = {**base, "old_start": None, "old_end": None}
    assert "prej čas ni znan, zdaj" in _variables(hass, unknown)["message"]
