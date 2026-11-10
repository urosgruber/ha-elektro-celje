"""Tests of the card registration in the frontend."""

import json
from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.elektro_celje.const import DOMAIN

BASE = Path(__file__).parent.parent / "custom_components" / "elektro_celje"
VERSION = json.loads((BASE / "manifest.json").read_text())["version"]


def test_card_file_exists() -> None:
    card = BASE / "frontend" / "elektro-celje-card.js"
    assert card.is_file()
    assert "customElements.define" in card.read_text(encoding="utf-8")


def test_manifest_depends_on_http_and_frontend() -> None:
    manifest = json.loads((BASE / "manifest.json").read_text())
    assert sorted(manifest["dependencies"]) == ["frontend", "http"]
    assert manifest["version"] == "2.3.1"


async def test_card_is_registered_once(hass: HomeAssistant, fake_frontend) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    from custom_components.elektro_celje import async_setup

    assert await async_setup(hass, {})

    fake_frontend.async_register_static_paths.assert_awaited_once()
    (paths,) = fake_frontend.async_register_static_paths.await_args.args
    assert len(paths) == 1
    assert paths[0].url_path == "/elektro_celje_static"
    assert Path(paths[0].path) == BASE / "frontend"
    assert paths[0].cache_headers is True
    assert hass.data[DATA_EXTRA_MODULE_URL] == {
        f"/elektro_celje_static/elektro-celje-card.js?v={VERSION}"
    }
