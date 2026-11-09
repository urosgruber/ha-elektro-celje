"""Tests for the YAML import, the repair issue and the diagnostics."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.elektro_celje.binary_sensor import async_setup_platform
from custom_components.elektro_celje.const import (
    CONF_REGION,
    CONF_STATION,
    DOMAIN,
    FEED_URL,
    TZ,
)
from custom_components.elektro_celje.diagnostics import (
    async_get_config_entry_diagnostics,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _feed(region: str) -> str:
    return (FIXTURES / f"rss_{region}_2026-11-09.xml").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _feeds(aioclient_mock: AiohttpClientMocker) -> None:
    for region in ("celje", "velenje", "krsko", "slovenj-gradec"):
        aioclient_mock.get(FEED_URL.format(region=region), text=_feed(region))


async def _import(hass: HomeAssistant, *sensors: dict) -> None:
    config = {"binary_sensor": [{"platform": DOMAIN, **s} for s in sensors]}
    assert await async_setup_component(hass, "binary_sensor", config)
    await hass.async_block_till_done()


def _owner() -> list[dict]:
    return [
        {
            "name": "TP Zabukovica",
            "region": "velenje",
            "search_station": "zabukovica papež",
        },
        {"name": "TP Lopata", "region": "celje", "search_station": "lopata oberžan"},
    ]


def _datas(hass: HomeAssistant) -> set[tuple[str, str, str]]:
    return {
        (e.title, e.data[CONF_REGION], e.data[CONF_STATION])
        for e in hass.config_entries.async_entries(DOMAIN)
    }


async def test_yaml_import_creates_entries(hass: HomeAssistant) -> None:
    await _import(hass, *_owner())
    assert _datas(hass) == {
        ("TP Zabukovica", "velenje", "zabukovica papež"),
        ("TP Lopata", "celje", "lopata oberžan"),
    }
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_yaml")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.translation_key == "deprecated_yaml"


async def test_yaml_import_twice_is_idempotent(hass: HomeAssistant) -> None:
    await _import(hass, *_owner())
    data = {"name": "TP Zabukovica", "region": "velenje", "station": "zabukovica papež"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # The platform function itself, called a second time for both sensors.
    for sensor in _owner():
        await async_setup_platform(hass, sensor, lambda *_: None)
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_yaml")


async def test_yaml_missing_keys_skip_import(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await _import(
        hass,
        {"name": "No station", "region": "celje"},
        {"name": " ", "region": "celje", "search_station": "abc"},
    )
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert caplog.text.count("Skipping a YAML sensor") == 2
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_yaml")


@pytest.mark.parametrize(
    ("value", "slug"),
    [
        ("Krško", "krsko"),
        ("Slovenj Gradec", "slovenj-gradec"),
        ("Celje", "celje"),
        ("Maribor", "all"),
    ],
)
async def test_yaml_region_with_accent_maps(
    hass: HomeAssistant, value: str, slug: str
) -> None:
    await _import(hass, {"name": "X", "region": value, "search_station": "abc"})
    assert _datas(hass) == {("X", slug, "abc")}


async def test_diagnostics_redacts(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(datetime(2026, 11, 9, 7, 40, tzinfo=TZ))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Moj Skrivni Dom",
        data={
            "name": "Moj Skrivni Dom",
            CONF_REGION: "velenje",
            CONF_STATION: "zabukovica papež",
        },
        options={"reminder_time": "17:00:00"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    diag = await async_get_config_entry_diagnostics(hass, entry)
    json.dumps(diag)  # must be JSON-safe
    assert diag["entry"]["data"]["name"] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_STATION] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_REGION] == "velenje"
    assert diag["entry"]["title"] == "**REDACTED**"
    assert diag["entry"]["options"] == {"reminder_time": "17:00:00"}
    config_part = json.dumps(diag["entry"])
    assert "Moj Skrivni Dom" not in config_part
    assert "zabukovica" not in config_part.lower()
    assert "Moj Skrivni Dom" not in json.dumps(diag)
    assert diag["raw_items"]["velenje"]
    assert {"title", "link", "text"} <= set(diag["raw_items"]["velenje"][0])
    assert len(diag["outages"]) == 1
    assert diag["records"]
