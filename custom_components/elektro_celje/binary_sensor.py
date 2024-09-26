"""Platform for the Elektro Celje sensor component."""
import logging
import pprint
import voluptuous as vol
from datetime import timedelta
from homeassistant.components.binary_sensor import BinarySensorEntity, PLATFORM_SCHEMA, BinarySensorDeviceClass
from homeassistant.const import CONF_NAME, CONF_REGION
from homeassistant.helpers.event import async_track_time_interval

from .elektro_celje_parser import ElektroCeljeParser

SCAN_INTERVAL = timedelta(minutes=60)

_LOGGER = logging.getLogger(__name__)
_LOGGER.info("Setting up Elektro Celje binary sensor platform...")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): vol.All(str),
    vol.Required("region"): vol.All(str),
    vol.Required("search_station"): vol.All(str),
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Elektro Celje sensor."""
    
    platform_name = "elektro_celje"

    _LOGGER.info("Setting up Elektro Celje binary sensor platform...")

    name = config.get(CONF_NAME, "Elektro Celje Sensor")
    region = config.get(CONF_REGION, "unknown")
    search_station = config.get("search_station", "unknown")
    unique_id = f"elektro_celje_{name.lower().replace(' ', '_')}_{region.lower()}"
    
    # Create an instance of ElektroCeljeParser
    elektro_celje_parser = ElektroCeljeParser(region)

    # Initialize the sensor and fetch data
    sensor = ElektroCeljeSensor(name, unique_id, region, search_station, elektro_celje_parser)
    await sensor.async_update()

    async_add_entities([sensor], update_before_add=True)

    # Log the configuration information
    _LOGGER.info(f"Config for Elektro Celje sensor: {config}")

class ElektroCeljeSensor(BinarySensorEntity):
    """Representation of a Elektro Celje sensor."""

    def __init__(self, name, unique_id, region, search_station, elektro_celje_parser):
        """Initialize the binary sensor."""
        self._name = name
        self._state = False
        self._unique_id = unique_id
        self._region = region
        self._search_station = search_station
        self._elektro_celje_parser = elektro_celje_parser
        self._attr_last_changed = None 
        self._published_date = None
        self._working_date = None
        self._start_date = None
        self._end_date = None
        self._description = None
        self._scan_interval = SCAN_INTERVAL

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this binary sensor."""
        return self._unique_id

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        return self._state

    @property
    def device_class(self):
        """Return the device class of the binary sensor."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def icon(self):
        """Return the icon to be shown for the binary sensor."""
        if self.is_on:
            return "mdi:transmission-tower-off"  # Icon for True state
        else:
            return "mdi:transmission-tower"  # Icon for False state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "region": self._region,
            "search_station": self._search_station,
            "last_changed": self._attr_last_changed,
            "published_date": self._published_date,
            "working_date": self._working_date,
            "start_date": self._start_date,
            "end_date": self._end_date,
            "description": self._description,
        }

    async def async_update(self, time_between_updates=None):
        """Update the binary sensor."""
        if self.hass is None:
            _LOGGER.info("Home Assistant object is not available. Skipping update.")
            return

        try:
            # Fetch data using ElektroCeljeParser
            elektro_celje_data = await self.hass.async_add_executor_job(self._elektro_celje_parser.fetch_data, self._search_station)

            # Set state based on the result
            self._state = elektro_celje_data.success

            # Update attributes
            self._published_date = elektro_celje_data.published_date
            self._working_date = elektro_celje_data.working_date
            self._start_date = elektro_celje_data.start_date
            self._end_date = elektro_celje_data.end_date
            self._description = elektro_celje_data.description

            # Update last changed timestamp
            self._attr_last_changed = self.hass.states.get(self.entity_id).last_changed

            # Set icon dynamically based on the state
            if self._state:
                self._attr_icon = "mdi:transmission-tower-off"
            else:
                self._attr_icon = "mdi:transmission-tower"

            # Log the update action
            _LOGGER.debug(f"Updated {self.name} binary sensor state to {self.is_on}")

            # Log the last changed timestamp
            _LOGGER.debug(f"{self.name} last changed: {self._attr_last_changed}")

        except Exception as e:
            _LOGGER.error(f"Error updating {self.name} binary sensor: {e}")

    async def async_remove(self):
        """Remove the entity."""
        _LOGGER.info(f"Removing {self.name} binary sensor")

        # Clean up resources, if any
        # ...

        # Call the parent class's async_remove method
        await super().async_remove()