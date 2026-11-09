"""Tests for the config flow, the reconfigure flow and the options flow."""

from datetime import datetime
from pathlib import Path

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.elektro_celje.const import (
    CONF_REGION,
    CONF_REMINDER_TIME,
    CONF_STATION,
    DOMAIN,
    EVENT_OUTAGE_REMOVED,
    FEED_URL,
    REGIONS,
    TZ,
)
from custom_components.elektro_celje.parser import normalize

FIXTURES = Path(__file__).parent / "fixtures"
USER_INPUT = {
    "name": "TP Zabukovica",
    CONF_REGION: "velenje",
    CONF_STATION: "Zabukovica Papež",
}


def _feed(region: str) -> str:
    return (FIXTURES / f"rss_{region}_2026-11-09.xml").read_text(encoding="utf-8")


def _mock_feeds(aioclient_mock: AiohttpClientMocker) -> None:
    for region in REGIONS:
        aioclient_mock.get(FEED_URL.format(region=region), text=_feed(region))


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


def _station_options(result) -> list[str]:
    for key, selector in result["data_schema"].schema.items():
        if key == CONF_STATION:
            return list(selector.config["options"])
    raise AssertionError("no station field")


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TP Zabukovica"
    assert result["data"] == USER_INPUT
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "velenje:zabukovica papez"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_station_suggestions_from_feed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await _start(hass)
    options = _station_options(result)
    assert "Zabukovica Papež" in options
    assert "Breg Pevec" in options
    assert options == sorted(options, key=normalize)


async def test_preview_shows_match(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    matches = result["description_placeholders"]["matches"]
    assert "08.30 in 11.00" in matches
    assert "Zabukovica Papež" in matches
    assert "Velenje" in matches


async def test_preview_no_match_text(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_STATION: "Nobena Postaja"}
    )
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["matches"] == (
        "No planned outage for this station now. This is normal."
    )


async def test_feed_down_still_allows_typed_station(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    for region in REGIONS:
        aioclient_mock.get(FEED_URL.format(region=region), status=500)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert _station_options(result) == []

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.config_entries.async_unload(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )


async def test_empty_station_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_STATION: "   "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_STATION: "station_required"}


async def test_duplicate_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    MockConfigEntry(
        domain=DOMAIN,
        title="Other",
        data={
            "name": "Other",
            CONF_REGION: "velenje",
            CONF_STATION: "zabukovica papez",
        },
        unique_id="velenje:zabukovica papez",
    ).add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import_creates_entry_and_aborts_duplicate(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_feeds(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=USER_INPUT
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"
    await hass.config_entries.async_unload(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )


async def test_options_reminder_time(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={"name": "Home", CONF_REGION: "velenje", CONF_STATION: "x"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_REMINDER_TIME: "19:30:00"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_REMINDER_TIME] == "19:30:00"


async def test_reconfigure_clears_alert_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer, hass_storage
) -> None:
    freezer.move_to(datetime(2026, 11, 9, 7, 40, tzinfo=TZ))
    _mock_feeds(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={"name": "Home", CONF_REGION: "velenje", CONF_STATION: "zabukovica papež"},
        unique_id="velenje:zabukovica papez",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    key = f"{DOMAIN}.{entry.entry_id}"
    old_ids = {r["notice_id"] for r in hass_storage[key]["data"]["records"]}
    assert old_ids == {"43322"}
    removed = async_capture_events(hass, EVENT_OUTAGE_REMOVED)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Home", CONF_REGION: "velenje", CONF_STATION: "Breg Pevec"},
    )
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert removed == []
    assert entry.data[CONF_STATION] == "Breg Pevec"
    assert entry.unique_id == "velenje:breg pevec"
    new_ids = {r["notice_id"] for r in hass_storage[key]["data"]["records"]}
    assert old_ids.isdisjoint(new_ids)
    assert new_ids == {"43288"}
    await hass.config_entries.async_unload(entry.entry_id)
