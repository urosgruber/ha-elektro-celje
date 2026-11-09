"""Config flow for Elektro Celje.

This is a placeholder so that Home Assistant can load config entries. The
setup form, the preview, reconfigure and the options arrive in a later task.
"""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class ElektroCeljeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of one location."""

    VERSION = 1
