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
    for key in ("titles", "when", "duration", "message"):
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
