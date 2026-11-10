"""Tests of the notification blueprint."""

from pathlib import Path

import pytest
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    """The sections flatten to all the public input keys."""
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
        "location_entities",
        "language",
        "title_detected",
        "title_reminder",
        "title_changed",
        "title_removed",
        "message_format",
    }


def test_blueprint_has_sections_and_min_version() -> None:
    """The inputs sit in four sections. The Texts section is collapsed."""
    blueprint = _data()["blueprint"]
    assert list(blueprint["input"]) == ["phone", "alerts", "places", "texts"]
    assert blueprint["input"]["texts"]["collapsed"] is True
    assert blueprint["homeassistant"]["min_version"] >= "2024.10.0"


def test_new_inputs_have_defaults() -> None:
    """Every new input has a default, so old automations keep working."""
    sections = _data()["blueprint"]["input"]
    flat = {k: v for sec in sections.values() for k, v in sec["input"].items()}
    assert flat["location_entities"]["default"] == []
    assert flat["language"]["default"] == "sl"
    for key in ("title_detected", "title_reminder", "title_changed", "title_removed"):
        assert flat[key]["default"] == ""
    assert flat["message_format"]["default"] == ""
    assert flat["message_format"]["selector"]["text"]["multiline"] is True
    assert flat["locations"]["default"] == ""
    entity = flat["location_entities"]["selector"]["entity"]
    assert entity["multiple"] is True
    assert entity["filter"] == [{"integration": "elektro_celje"}]


def test_blueprint_triggers() -> None:
    """The blueprint listens to the four events."""
    triggers = _data()["triggers"]
    assert {t["event_type"] for t in triggers} == EVENTS
    assert all(t["trigger"] == "event" for t in triggers)


def test_boolean_defaults() -> None:
    """All four booleans default to true."""
    inputs = _data()["blueprint"]["input"]["alerts"]["input"]
    for key in ("on_detected", "on_reminder", "on_changed", "on_removed"):
        assert inputs[key]["default"] is True


EV = "elektro_celje_outage_"
DEFAULTS = {
    "lang": "sl",
    "custom_titles": {},
    "message_format": "",
}


def _variables(hass, data: dict, event: str = "detected", **inputs) -> dict:
    """Render the action variables of the blueprint for one event."""
    spec = _data()["actions"][0]["variables"]
    out: dict = {
        **DEFAULTS,
        **inputs,
        "d": {"location": "Dom", **data},
        "trigger": {"event": {"event_type": EV + event}},
    }
    for key, value in spec.items():
        if key == "d":
            continue
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


# --- Slovenian texts stay as they were (pinned) --------------------------

DETECTED = {
    "start": "2026-11-12T08:00:00+01:00",
    "end": "2026-11-12T14:00:00+01:00",
    "all_day": False,
    "duration_minutes": 360,
    "station": "TP lopata 1",
    "text": "Izklop",
    "link": "https://example.test/n/1",
}
CHANGED = {
    **DETECTED,
    "start": "2026-11-13T08:00:00+01:00",
    "end": "2026-11-13T10:00:00+01:00",
    "duration_minutes": 120,
    "old_start": "2026-11-12T08:00:00+01:00",
    "old_end": "2026-11-12T14:00:00+01:00",
}
ALL_DAY = {
    **DETECTED,
    "start": "2026-11-12T00:00:00+01:00",
    "end": "2026-11-13T00:00:00+01:00",
    "all_day": True,
    "duration_minutes": 1440,
}
UNKNOWN = {
    "start": None,
    "end": None,
    "all_day": False,
    "duration_minutes": None,
    "text": "Izklop na Lopati",
}
REMINDER = {**DETECTED, "start": "2026-11-12T08:30:00+01:00",
            "end": "2026-11-12T11:00:00+01:00", "duration_minutes": 150}  # fmt: skip

SLOVENIAN = [
    ("detected", DETECTED, "Načrtovan izklop",
     "TP lopata: 12. 11. 2026, 08:00–14:00 (6 h)"),
    ("reminder", REMINDER, "Jutri izklop",
     "TP lopata: 12. 11. 2026, 08:30–11:00 (2 h 30 min)"),
    ("changed", CHANGED, "Izklop spremenjen",
     "TP lopata: prej 12. 11. 2026, 08:00–14:00, zdaj 13. 11. 2026, 08:00–10:00 (2 h)"),
    ("removed", DETECTED, "Izklop ni več objavljen",
     "TP lopata: 12. 11. 2026, 08:00–14:00 (6 h)"),
    ("detected", ALL_DAY, "Načrtovan izklop",
     "TP lopata: 12. 11. 2026, ves dan (24 h)"),
    ("detected", UNKNOWN, "Načrtovan izklop",
     "TP lopata: čas ni znan. Izklop na Lopati"),
]  # fmt: skip

ENGLISH = [
    ("detected", DETECTED, "Planned power outage",
     "TP lopata: 12 Nov 2026, 08:00–14:00 (6 h)"),
    ("reminder", REMINDER, "Power outage tomorrow",
     "TP lopata: 12 Nov 2026, 08:30–11:00 (2 h 30 min)"),
    ("changed", CHANGED, "Power outage changed",
     "TP lopata: previously 12 Nov 2026, 08:00–14:00, "
     "now 13 Nov 2026, 08:00–10:00 (2 h)"),
    ("removed", DETECTED, "Power outage no longer listed",
     "TP lopata: 12 Nov 2026, 08:00–14:00 (6 h)"),
    ("detected", ALL_DAY, "Planned power outage",
     "TP lopata: 12 Nov 2026, all day (24 h)"),
    ("detected", UNKNOWN, "Planned power outage",
     "TP lopata: time unknown. Izklop na Lopati"),
]  # fmt: skip


@pytest.mark.parametrize(("event", "data", "title", "message"), SLOVENIAN)
async def test_slovenian_texts_are_unchanged(hass, event, data, title, message) -> None:
    """The default inputs give the same Slovenian texts as before."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    out = _variables(hass, {"location": "TP lopata", **data}, event)
    assert out["title"] == title
    assert out["message"] == message


@pytest.mark.parametrize(("event", "data", "title", "message"), ENGLISH)
async def test_english_texts(hass, event, data, title, message) -> None:
    """The English built-in texts have the same shape as the Slovenian ones."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    out = _variables(hass, {"location": "TP lopata", **data}, event, lang="en")
    assert out["title"] == title
    assert out["message"] == message


async def test_custom_title_and_message_with_every_placeholder(hass) -> None:
    """Each placeholder gets its value, in the title and in the message."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    out = _variables(
        hass,
        {"location": "Dom", **DETECTED},
        custom_titles={EV + "detected": "Izklop {location}"},
        message_format=(
            "{location} | {when} | [{old_when}] | {duration} | "
            "{station} | {text} | {link}"
        ),
    )
    assert out["title"] == "Izklop Dom"
    assert out["message"] == (
        "Dom | 12. 11. 2026, 08:00–14:00 | [] | 6 h | "
        "TP lopata 1 | Izklop | https://example.test/n/1"
    )


async def test_custom_message_with_old_when(hass) -> None:
    """{old_when} has the earlier time of a changed outage."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    out = _variables(
        hass,
        {"location": "Dom", **CHANGED},
        "changed",
        lang="en",
        message_format="{location}\nwas {old_when}\nnow {when}",
    )
    assert out["message"] == (
        "Dom was 12 Nov 2026, 08:00–14:00 now 13 Nov 2026, 08:00–10:00"
    )


async def test_empty_custom_fields_give_built_in_texts(hass) -> None:
    """Empty or blank custom texts, and an empty result, use the built-in texts."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    built_in = _variables(hass, {"location": "Dom", **DETECTED})
    for blank in ("", "  ", "{old_when}"):
        custom = {
            "custom_titles": {EV + "detected": blank},
            "message_format": blank,
        }
        out = _variables(hass, {"location": "Dom", **DETECTED}, **custom)
        assert out["title"] == built_in["title"]
        assert out["message"] == built_in["message"]


async def test_feed_text_is_not_rendered_as_a_template(hass) -> None:
    """Text from the feed appears literally: no template, no second pass."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    data = {
        "location": "Dom",
        **DETECTED,
        "text": "{{ 7*7 }} {location}",
        "station": "{text} {{ 1+1 }}",
        "link": "{% if 1 %}x{% endif %}\x01" + "0\x01",
    }
    out = _variables(
        hass,
        data,
        custom_titles={EV + "detected": "{text}"},
        message_format="{station} / {text} / {link}",
    )
    assert out["title"] == "{{ 7*7 }} {location}"
    assert out["message"] == (
        "{text} {{ 1+1 }} / {{ 7*7 }} {location} / {% if 1 %}x{% endif %}0"
    )
    assert "49" not in out["message"]
    assert "Dom" not in out["message"]


# --- Location filter --------------------------------------------------------


async def _filter(hass, event_data: dict, entities, names="") -> bool:
    condition = _data()["conditions"][1]["value_template"]
    result = Template(condition, hass).async_render(
        {
            "location_entities": entities,
            "location_filter": names,
            "trigger": {"event": {"data": event_data}},
        },
        parse_result=True,
    )
    return result is True


@pytest.fixture
async def picker(hass) -> dict:
    """Two config entries, each with one entity."""
    registry = er.async_get(hass)
    out = {}
    for name in ("a", "b"):
        entry = MockConfigEntry(domain="elektro_celje", title=name)
        entry.add_to_hass(hass)
        reg = registry.async_get_or_create(
            "sensor", "elektro_celje", name, config_entry=entry
        )
        out[name] = (entry.entry_id, reg.entity_id)
    return out


async def test_filter_empty_means_all(hass) -> None:
    """With no picked entity and no name every outage passes."""
    event = {"entry_id": "x", "location": "Dom"}
    assert await _filter(hass, event, [])
    assert await _filter(hass, event, [], "")
    assert await _filter(hass, event, None, None)


async def test_filter_by_picker(hass, picker) -> None:
    """A picked entity selects the config entry of its location."""
    entry_a, entity_a = picker["a"]
    entry_b, _ = picker["b"]
    assert await _filter(hass, {"entry_id": entry_a, "location": "A"}, [entity_a])
    assert not await _filter(hass, {"entry_id": entry_b, "location": "B"}, [entity_a])


async def test_filter_by_name(hass) -> None:
    """A name selects a location without case or space problems."""
    assert await _filter(
        hass, {"entry_id": "x", "location": "Dom"}, [], " dom , Služba"
    )
    assert not await _filter(hass, {"entry_id": "x", "location": "Vikend"}, [], "dom")


async def test_filter_union_of_picker_and_name(hass, picker) -> None:
    """An outage passes when the picker or the name matches."""
    entry_a, entity_a = picker["a"]
    entry_b, _ = picker["b"]
    by_picker = {"entry_id": entry_a, "location": "A"}
    by_name = {"entry_id": entry_b, "location": "Dom"}
    neither = {"entry_id": entry_b, "location": "Vikend"}
    assert await _filter(hass, by_picker, [entity_a], "dom")
    assert await _filter(hass, by_name, [entity_a], "dom")
    assert not await _filter(hass, neither, [entity_a], "dom")


async def test_filter_single_string_entity(hass, picker) -> None:
    """A single string works like a list of one entity."""
    entry_a, entity_a = picker["a"]
    entry_b, _ = picker["b"]
    assert await _filter(hass, {"entry_id": entry_a, "location": "A"}, entity_a)
    assert not await _filter(hass, {"entry_id": entry_b, "location": "B"}, entity_a)


async def test_filter_unknown_picked_entity_does_not_mean_all(hass) -> None:
    """A picked entity that no longer exists must not widen the filter."""
    assert not await _filter(
        hass, {"entry_id": "x", "location": "Dom"}, ["sensor.gone"]
    )
