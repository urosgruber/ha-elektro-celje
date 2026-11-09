"""Tests of the dashboard card template."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elektro_celje.cardtext import build_card
from custom_components.elektro_celje.const import TZ
from custom_components.elektro_celje.location import LocationData
from custom_components.elektro_celje.models import Outage, ParseStatus

CARD = Path("docs/dashboard-card.yaml")


def _content() -> str:
    return load_yaml(str(CARD))["content"]


async def _setup(hass: HomeAssistant, name: str = "Dom") -> None:
    """Create a location with a device and the two entities."""
    entry = MockConfigEntry(domain="elektro_celje", title=name)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("elektro_celje", entry.entry_id)},
        name=name,
    )
    registry = er.async_get(hass)
    slug = name.lower()
    for domain, suffix in (
        ("sensor", "planned_outages"),
        ("binary_sensor", "feed_problem"),
    ):
        registry.async_get_or_create(
            domain,
            "elektro_celje",
            f"{entry.entry_id}_{suffix}",
            suggested_object_id=f"{slug}_{suffix}",
            config_entry=entry,
            device_id=device.id,
        )
        # integration_entities reads the live entity sources.
        entity_sources(hass)[f"{domain}.{slug}_{suffix}"] = {
            "domain": "elektro_celje",
            "config_entry": entry.entry_id,
        }


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=TZ)


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def _o(
    start: datetime | None,
    end: datetime | None = None,
    status: ParseStatus = ParseStatus.OK,
    all_day: bool = False,
    key: str = "a",
) -> Outage:
    if start and end is None:
        end = start + timedelta(hours=2, minutes=30)
    return Outage(
        key=key,
        notice_id=key,
        region="celje",
        station_text="TP Zabukovica",
        text="Izklop zaradi vzdrževanja",
        link="https://example.com",
        status=status if start else ParseStatus.FAILED,
        start=start,
        end=end,
        all_day=all_day,
    )


def _set(
    hass: HomeAssistant,
    outages: list[Outage],
    name: str = "dom",
    problem_hours: float | None = None,
    last_success: datetime | None = None,
) -> None:
    """Set the states of one location, as the integration writes them."""
    success = last_success or NOW
    problem = NOW - timedelta(hours=problem_hours) if problem_hours else None
    data = LocationData(
        outages=outages,
        planned=[o for o in outages if o.end is None or o.end > NOW],
        records={},
        feed_urls=[],
        last_attempt=success,
        last_success=success,
        problem_since=problem,
        feed_ok=problem is None,
    )
    attrs = build_card(data, name.capitalize(), NOW, "en")
    hass.states.async_set(
        f"sensor.{name}_planned_outages",
        str(len(data.planned)),
        {"last_success": success.astimezone(UTC).isoformat(), **attrs},
    )
    hass.states.async_set(
        f"binary_sensor.{name}_feed_problem", "off", {"problem_since": None}
    )


async def _render(hass: HomeAssistant) -> str:
    return Template(_content(), hass).async_render(parse_result=False).strip()


async def test_hidden_when_nothing(hass: HomeAssistant, freezer) -> None:
    """The card renders nothing when there is nothing to show."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [])
    assert await _render(hass) == ""


async def test_one_outage_tomorrow(hass: HomeAssistant, freezer) -> None:
    """One planned outage shows only the banner and the footer."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [_o(_t(10, 8, 30))])
    text = await _render(hass)
    assert 'alert-type="warning"' in text
    assert "Tomorrow, Tue 10 Nov · 08:30–11:00" in text
    assert "Dom · 2 h 30 min · tomorrow" in text
    assert "Also planned" not in text
    assert "Ended today" not in text
    assert "Checked Mon 9 Nov 2026, 12:00 · elektro-celje.si" in text


async def test_three_outages_two_locations(hass: HomeAssistant, freezer) -> None:
    """The banner shows once. The rest is grouped by day."""
    freezer.move_to(NOW)
    await _setup(hass, "Dom")
    await _setup(hass, "Garaza")
    _set(hass, [_o(_t(12, 8), _t(12, 14), key="a"), _o(_t(10, 8, 30), key="b")])
    _set(hass, [_o(_t(12, 9), _t(12, 10), key="c")], name="garaza")
    text = await _render(hass)
    assert text.count("ha-alert") == 2
    assert text.count("08:30") == 1
    assert "Also planned" in text
    assert text.count("**Thu 12 Nov**") == 1
    assert "- **Dom** · 08:00–14:00 · 6 h · in 3 days" in text
    assert "- **Garaza** · 09:00–10:00 · 1 h · in 3 days" in text
    assert text.index("Tomorrow") < text.index("Also planned")


async def test_live_outage(hass: HomeAssistant, freezer) -> None:
    """An active outage shows the error banner with the end."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [_o(_t(9, 11), _t(9, 13)), _o(_t(10, 8), key="b")])
    text = await _render(hass)
    assert 'alert-type="error"' in text
    assert "Outage now · 11:00–13:00" in text
    assert "until 13:00" in text
    assert "Also planned" in text
    assert 'alert-type="warning"' not in text


async def test_feed_problem_info_alert(hass: HomeAssistant, freezer) -> None:
    """A long feed problem shows the info alert, also with no outage."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [], problem_hours=2, last_success=NOW - timedelta(hours=4))
    text = await _render(hass)
    assert 'alert-type="info"' in text
    assert "Cannot read the Elektro Celje feed." in text
    assert "Last good check: today 08:00." in text
    assert "Checked" in text


async def test_short_feed_problem_hidden(hass: HomeAssistant, freezer) -> None:
    """A problem that is shorter than one hour shows nothing."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [], problem_hours=0.3)
    assert await _render(hass) == ""


async def test_only_ended_today(hass: HomeAssistant, freezer) -> None:
    """Ended outages alone show the small section and the footer."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [_o(_t(9, 8, 30), _t(9, 11))])
    text = await _render(hass)
    assert "ha-alert" not in text
    assert "Also planned" not in text
    assert "Ended today" in text
    assert "<small>*✓ Dom · 08:30–11:00 · ended*</small>" in text
    assert "font" not in text
    assert text.index("Ended today") < text.index("Checked")


async def test_ended_after_planned_and_problem(hass: HomeAssistant, freezer) -> None:
    """The order is: info alert, banner, list, ended section, footer."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(
        hass,
        [
            _o(_t(9, 8, 30), _t(9, 11), key="e"),
            _o(_t(10, 8), key="b"),
            _o(_t(11, 8), key="c"),
        ],
        problem_hours=2,
    )
    text = await _render(hass)
    order = [
        text.index(part)
        for part in (
            'alert-type="info"',
            'alert-type="warning"',
            "Also planned",
            "Ended today",
            "Checked",
        )
    ]
    assert order == sorted(order)


async def test_slovenian_labels(hass: HomeAssistant, freezer) -> None:
    """The card has no text of its own. It prints the labels of the sensor."""
    freezer.move_to(NOW)
    await _setup(hass)
    _set(hass, [_o(_t(9, 8, 30), _t(9, 11)), _o(_t(10, 8), key="b")])
    state = hass.states.get("sensor.dom_planned_outages")
    attrs = {
        **state.attributes,
        **build_card(
            LocationData(
                outages=[_o(_t(9, 8, 30), _t(9, 11)), _o(_t(10, 8), key="b")],
                planned=[_o(_t(10, 8), key="b")],
                records={},
                feed_urls=[],
                last_attempt=NOW,
                last_success=NOW,
                problem_since=None,
                feed_ok=True,
            ),
            "Dom",
            NOW,
            "sl",
        ),
    }
    hass.states.async_set(state.entity_id, state.state, attrs)
    text = await _render(hass)
    assert "Končalo se je danes" in text
    assert "Preverjeno" in text


def test_card_is_short() -> None:
    """The card only loops and prints."""
    assert len(_content().splitlines()) <= 60


def test_readme_card_matches_file() -> None:
    """The card in the README equals docs/dashboard-card.yaml."""
    readme = Path("README.md").read_text()
    block = readme.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert block == CARD.read_text().rstrip("\n")
