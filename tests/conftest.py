"""Shared test fixtures."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""
    yield


@pytest.fixture(autouse=True)
def fake_frontend(hass):
    """Stand in for the http and frontend integrations.

    The real frontend needs the frontend package, which the tests do not
    install. The fake records the static paths and the extra module URLs.
    """
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.data[DATA_EXTRA_MODULE_URL] = set()
    hass.config.components.update({"http", "frontend"})
    yield hass.http
