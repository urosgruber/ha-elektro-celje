"""Tests of the dashboard card template."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry

CARD = Path("docs/dashboard-card.yaml")


def _content() -> str:
    return load_yaml(str(CARD))["content"]


async def _setup(hass: HomeAssistant, name: str = "Dom") -> None:
    """Create a location with a device and the two entities."""
    await hass.config.async_set_time_zone("Europe/Ljubljana")
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


def _outage(start: datetime | None, hours: float = 2.5) -> dict:
    end = start + timedelta(hours=hours) if start else None
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "all_day": False,
        "status": "ok" if start else "failed",
        "station": "TP Zabukovica",
        "region": "celje",
        "text": "Izklop zaradi vzdrževanja",
        "link": "https://example.com",
    }


def _set_states(
    hass: HomeAssistant,
    outages: list[dict],
    problem_since: datetime | None = None,
    last_success: datetime | None = None,
    name: str = "dom",
) -> None:
    last = last_success or dt_util.now()
    hass.states.async_set(
        f"sensor.{name}_planned_outages",
        str(len(outages)),
        {"outages": outages, "feed_urls": [], "last_success": last.isoformat()},
    )
    hass.states.async_set(
        f"binary_sensor.{name}_feed_problem",
        "on" if problem_since else "off",
        {"problem_since": problem_since.isoformat() if problem_since else None},
    )


def _day(offset: int, hour: int, minute: int = 0) -> datetime:
    base = dt_util.now() + timedelta(days=offset)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


async def _render(hass: HomeAssistant) -> str:
    return Template(_content(), hass).async_render(parse_result=False).strip()


async def test_hidden_when_nothing_planned(hass: HomeAssistant) -> None:
    """The card renders nothing when there is no outage and no problem."""
    await _setup(hass)
    _set_states(hass, [])
    assert await _render(hass) == ""


async def test_hidden_on_short_problem(hass: HomeAssistant) -> None:
    """A problem that is younger than one hour does not show the card."""
    await _setup(hass)
    _set_states(hass, [], problem_since=dt_util.now() - timedelta(minutes=20))
    assert await _render(hass) == ""


async def test_one_outage_tomorrow(hass: HomeAssistant) -> None:
    """One planned outage shows only the banner."""
    await _setup(hass)
    _set_states(hass, [_outage(_day(1, 8, 30))])
    text = await _render(hass)
    assert "08:30–11:00" in text
    assert "Dom" in text
    assert "Tomorrow" in text
    assert "Also planned" not in text
    assert "Checked" in text
    assert "elektro-celje.si" in text


async def test_three_outages(hass: HomeAssistant) -> None:
    """The banner outage is not repeated in the list."""
    await _setup(hass)
    _set_states(
        hass,
        [_outage(_day(3, 8), 6), _outage(_day(1, 8, 30)), _outage(_day(4, 8), 2)],
    )
    text = await _render(hass)
    assert "Also planned" in text
    assert text.rsplit("Checked", 1)[0].count("08:30") == 1
    assert "08:00 – 14:00 · 6 h" in text
    assert "08:00 – 10:00 · 2 h" in text


async def test_outage_now(hass: HomeAssistant) -> None:
    """An active outage shows the live banner with the end."""
    await _setup(hass)
    start = dt_util.now() - timedelta(hours=1)
    _set_states(hass, [_outage(start, 2.0), _outage(_day(2, 8))])
    text = await _render(hass)
    assert "Outage now" in text
    assert 'alert-type="error"' in text
    assert "ends in" in text
    assert "Also planned" in text


async def test_two_locations(hass: HomeAssistant) -> None:
    """Outages of two locations appear as separate rows with their names."""
    await _setup(hass, "Dom")
    await _setup(hass, "Garaza")
    _set_states(hass, [_outage(_day(1, 8, 30))])
    _set_states(hass, [_outage(_day(2, 9))], name="garaza")
    text = await _render(hass)
    assert "Dom" in text
    assert "Garaza" in text


async def test_failed_notice_shows_time_unknown(hass: HomeAssistant) -> None:
    """An outage without a time shows the unknown-time text."""
    await _setup(hass)
    _set_states(hass, [_outage(None)])
    text = await _render(hass)
    assert "time unknown" in text
    assert "Izklop zaradi vzdrževanja" in text


async def test_feed_problem_without_outages(hass: HomeAssistant) -> None:
    """A problem older than one hour shows state 4."""
    await _setup(hass)
    _set_states(
        hass,
        [],
        problem_since=dt_util.now() - timedelta(hours=2),
        last_success=dt_util.now() - timedelta(hours=4),
    )
    text = await _render(hass)
    assert "Cannot read the Elektro Celje feed" in text
    assert "Also planned" not in text
    assert "Checked" in text


async def test_all_day_outage(hass: HomeAssistant) -> None:
    """An all-day outage shows the all-day text and no clock time."""
    await _setup(hass)
    start = _day(1, 0)
    outage = _outage(start, 24)
    outage.update(all_day=True, status="date_only")
    _set_states(hass, [outage])
    text = await _render(hass)
    assert "all day" in text
    assert "00:00" not in text.rsplit("Checked", 1)[0]
    assert "24 h" not in text


async def test_utc_outage_is_shown_in_local_time(hass: HomeAssistant) -> None:
    """An outage in UTC near midnight shows the local date and time."""
    await _setup(hass)
    local = _day(2, 0, 30)
    utc = local.astimezone(UTC)
    _set_states(hass, [_outage(utc, 1.0)])
    text = await _render(hass)
    assert "00:30–01:30" in text
    assert local.strftime("%a %-d %b") in text


def test_readme_card_matches_file() -> None:
    """The card in the README equals docs/dashboard-card.yaml."""
    readme = Path("README.md").read_text()
    block = readme.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert block == CARD.read_text().rstrip("\n")


def _ended(hour: int = 8, minute: int = 30) -> dict:
    """An outage that ended today, from the `ended_today` attribute."""
    return _outage(_day(0, hour, minute))


def _set_ended(hass: HomeAssistant, outages: list[dict], ended: list[dict]) -> None:
    _set_states(hass, outages)
    state = hass.states.get("sensor.dom_planned_outages")
    hass.states.async_set(
        state.entity_id, state.state, {**state.attributes, "ended_today": ended}
    )


async def test_only_ended_today(hass: HomeAssistant) -> None:
    """An ended outage alone shows the small section, no banner."""
    await _setup(hass)
    _set_ended(hass, [], [_ended()])
    text = await _render(hass)
    assert "Ended today" in text
    assert "Dom" in text
    assert "<small>*✓ Dom · 08:30–11:00 · ended*</small>" in text
    assert "ha-alert" not in text
    assert "font" not in text
    assert "Checked" in text


async def test_ended_today_after_planned(hass: HomeAssistant) -> None:
    """The planned outage keeps the banner. The ended section comes after."""
    await _setup(hass)
    _set_ended(hass, [_outage(_day(1, 9))], [_ended()])
    text = await _render(hass)
    assert text.count("ha-alert") == 2
    assert 'alert-type="warning"' in text
    assert text.index("Ended today") > text.rindex("</ha-alert>")
    assert text.index("Ended today") < text.index("Checked")


async def test_ended_today_all_day(hass: HomeAssistant) -> None:
    """An all-day ended outage shows the all-day text."""
    await _setup(hass)
    outage = _outage(_day(0, 0), 24)
    outage.update(all_day=True, status="date_only")
    _set_ended(hass, [], [outage])
    text = await _render(hass)
    assert "Ended today" in text
    assert "all day" in text


async def test_hidden_without_ended_today(hass: HomeAssistant) -> None:
    """No planned outage and no ended outage keeps the card empty."""
    await _setup(hass)
    _set_ended(hass, [], [])
    assert await _render(hass) == ""


async def test_ended_today_after_feed_problem(hass: HomeAssistant) -> None:
    """With a feed problem, the ended section follows the info alert."""
    await _setup(hass)
    _set_ended(hass, [], [_ended()])
    _set_states(hass, [], problem_since=dt_util.now() - timedelta(hours=2))
    state = hass.states.get("sensor.dom_planned_outages")
    hass.states.async_set(
        state.entity_id, state.state, {**state.attributes, "ended_today": [_ended()]}
    )
    text = await _render(hass)
    assert 'alert-type="info"' in text
    assert text.index("Ended today") > text.rindex("</ha-alert>")
    assert text.index("Ended today") < text.index("Checked")
