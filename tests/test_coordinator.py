"""Tests for the feed download and the region coordinator."""

from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.elektro_celje.const import DOMAIN, FEED_URL, SCAN_INTERVAL
from custom_components.elektro_celje.coordinator import (
    async_acquire_region,
    async_release_region,
)

FIXTURES = Path(__file__).parent / "fixtures"
URL = FEED_URL.format(region="velenje")


def _feed() -> str:
    return (FIXTURES / "rss_velenje_2026-11-09.xml").read_text(encoding="utf-8")


async def test_fetch_and_parse_velenje(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text=_feed())
    coordinator = await async_acquire_region(hass, "velenje")
    assert coordinator.last_update_success
    assert len(coordinator.data.notices) == 9
    assert coordinator.last_success is not None
    assert coordinator.last_attempt is not None
    assert coordinator.problem_since is None
    assert coordinator.region == "velenje"
    assert coordinator.feed_url == URL
    await async_release_region(hass, "velenje")


async def test_http_error_keeps_last_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    aioclient_mock.get(URL, text=_feed())
    coordinator = await async_acquire_region(hass, "velenje")
    first = coordinator.data
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=500)
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    failed_at = dt_util.utcnow()
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert coordinator.data is first
    assert coordinator.problem_since == failed_at
    assert coordinator.last_attempt == failed_at
    await async_release_region(hass, "velenje")


async def test_non_rss_body_is_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text="<html><body>Maintenance</body></html>")
    coordinator = await async_acquire_region(hass, "velenje")
    assert not coordinator.last_update_success
    assert coordinator.data is None
    assert coordinator.problem_since is not None
    await async_release_region(hass, "velenje")


async def test_truncated_xml_is_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text=_feed()[:500])
    coordinator = await async_acquire_region(hass, "velenje")
    assert not coordinator.last_update_success
    assert coordinator.data is None
    await async_release_region(hass, "velenje")


async def test_oversize_body_is_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text="x" * 1_100_000)
    coordinator = await async_acquire_region(hass, "velenje")
    assert not coordinator.last_update_success
    await async_release_region(hass, "velenje")


async def test_recovery_clears_problem_since(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    aioclient_mock.get(URL, status=503)
    coordinator = await async_acquire_region(hass, "velenje")
    assert coordinator.problem_since is not None
    first_problem = coordinator.problem_since
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.problem_since == first_problem
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, text=_feed())
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert coordinator.problem_since is None
    assert len(coordinator.data.notices) == 9
    await async_release_region(hass, "velenje")


async def test_shared_coordinator_one_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text=_feed())
    first = await async_acquire_region(hass, "velenje")
    second = await async_acquire_region(hass, "velenje")
    assert first is second
    assert aioclient_mock.call_count == 1
    await async_release_region(hass, "velenje")
    assert "velenje" in hass.data[DOMAIN]["regions"]
    await async_release_region(hass, "velenje")
    assert "velenje" not in hass.data[DOMAIN]["regions"]
    assert first._shutdown_requested


async def test_user_agent_header(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(URL, text=_feed())
    await async_acquire_region(hass, "velenje")
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["User-Agent"] == (
        "HomeAssistant-elektro_celje/2.0.0 "
        "(+https://github.com/urosgruber/ha-elektro-celje)"
    )
    await async_release_region(hass, "velenje")
