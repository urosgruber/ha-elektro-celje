"""Config flow for Elektro Celje: add, check and reconfigure a location."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)
from homeassistant.helpers.translation import async_get_translations

from .client import FeedError, async_fetch_feed
from .const import (
    ALL_REGIONS,
    CONF_NOTIFY_TARGETS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_FROM,
    CONF_QUIET_HOURS,
    CONF_QUIET_TO,
    CONF_REGION,
    CONF_REMINDER_TIME,
    CONF_STATION,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
    QUIET_ENTITY_DOMAINS,
    REGIONS,
    SECTION_ADVANCED,
)
from .location import async_clear_alert_state
from .matching import matches
from .models import Notice
from .notifications import NotifySettings, mobile_app_targets
from .parser import FeedFormatError, normalize, parse_feed

_LOGGER = logging.getLogger(__name__)

CONF_NAME = "name"
NO_MATCH_TEXT = "No planned outage for this station now. This is normal."


_MARKDOWN_RE = re.compile(r"([\\`*_\[\]!<>])")


def _escape_markdown(text: str) -> str:
    """Escape feed text, so it cannot add links, images or HTML to the form."""
    return _MARKDOWN_RE.sub(r"\\\1", text)


def _region_slugs(region: str) -> list[str]:
    return list(REGIONS) if region == ALL_REGIONS else [region]


async def _async_notices(hass: HomeAssistant, region: str) -> list[Notice]:
    """Download the notices of the region now. A failed feed adds no notices."""
    session = async_get_clientsession(hass)
    slugs = _region_slugs(region)
    results = await asyncio.gather(
        *(async_fetch_feed(session, slug) for slug in slugs),
        return_exceptions=True,
    )
    notices: list[Notice] = []
    for slug, result in zip(slugs, results, strict=True):
        if isinstance(result, BaseException):
            if not isinstance(result, FeedError):
                raise result
            _LOGGER.debug("Feed %s is not available: %s", slug, result)
            continue
        try:
            notices.extend(parse_feed(result, slug))
        except FeedFormatError as err:
            _LOGGER.debug("Feed %s is not valid: %s", slug, err)
    return notices


def _station_options(notices: list[Notice]) -> list[str]:
    names: dict[str, str] = {}
    for notice in notices:
        for name in notice.station_names:
            names.setdefault(normalize(name), name)
    return sorted(names.values(), key=normalize)


def _phones_selector(phones: Mapping[str, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=name, label=label)
                for name, label in phones.items()
            ],
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _phones_field(phones: Mapping[str, str], suggested: list[str]) -> dict[Any, Any]:
    """Return the "Notify phones" field, or nothing when no phone exists.

    The field is optional with a suggested value, not a default. An empty
    choice then stays empty and means "notifications off".
    """
    if not phones:
        return {}
    return {
        vol.Optional(
            CONF_NOTIFY_TARGETS, description={"suggested_value": suggested}
        ): _phones_selector(phones)
    }


def _schema(
    stations: list[str],
    defaults: Mapping[str, Any],
    phones: Mapping[str, str] | None = None,
) -> vol.Schema:
    extra = (
        _phones_field(phones, list(defaults.get(CONF_NOTIFY_TARGETS, [])))
        if phones is not None
        else {}
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)
            ): TextSelector(),
            vol.Required(
                CONF_REGION, default=defaults.get(CONF_REGION, ALL_REGIONS)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[ALL_REGIONS, *REGIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_REGION,
                )
            ),
            vol.Required(
                CONF_STATION, default=defaults.get(CONF_STATION, vol.UNDEFINED)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=stations,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            **extra,
        }
    )


def unique_id_for(region: str, station: str) -> str:
    """Return the unique ID of a location."""
    return f"{region}:{normalize(station)}"


class ElektroCeljeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of one location."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._options: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> ElektroCeljeOptionsFlow:
        """Return the options flow."""
        return ElektroCeljeOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the name, the region and the station."""
        return await self._async_form_step("user", user_input, ALL_REGIONS, {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the region or the station of a location."""
        entry = self._get_reconfigure_entry()
        return await self._async_form_step(
            "reconfigure", user_input, entry.data[CONF_REGION], dict(entry.data)
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Create a location from imported data, without the confirm step."""
        try:
            data = {
                CONF_NAME: str(import_data[CONF_NAME]).strip(),
                CONF_REGION: import_data[CONF_REGION],
                CONF_STATION: str(import_data[CONF_STATION]).strip(),
            }
        except KeyError:
            return self.async_abort(reason="invalid_import")
        if (
            not data[CONF_NAME]
            or not data[CONF_STATION]
            or data[CONF_REGION] not in (ALL_REGIONS, *REGIONS)
        ):
            return self.async_abort(reason="invalid_import")
        await self.async_set_unique_id(
            unique_id_for(data[CONF_REGION], data[CONF_STATION])
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=data[CONF_NAME], data=data)

    async def _async_form_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        suggestion_region: str,
        defaults: Mapping[str, Any],
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            station = user_input[CONF_STATION].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            if not station:
                errors[CONF_STATION] = "station_required"
            if not errors:
                region = user_input[CONF_REGION]
                unique_id = unique_id_for(region, station)
                await self.async_set_unique_id(unique_id)
                if self.source == "reconfigure":
                    own_id = self._get_reconfigure_entry().entry_id
                    if any(
                        other.unique_id == unique_id and other.entry_id != own_id
                        for other in self._async_current_entries(include_ignore=False)
                    ):
                        return self.async_abort(reason="already_configured")
                else:
                    self._abort_if_unique_id_configured()
                self._data = {
                    CONF_NAME: name,
                    CONF_REGION: region,
                    CONF_STATION: station,
                }
                if step_id == "user":
                    self._options = {
                        CONF_NOTIFY_TARGETS: list(
                            user_input.get(CONF_NOTIFY_TARGETS, [])
                        )
                    }
                return await self.async_step_confirm()
            # A cleared phone list is not in user_input. It must stay cleared.
            defaults = {
                **user_input,
                CONF_NOTIFY_TARGETS: list(user_input.get(CONF_NOTIFY_TARGETS, [])),
            }
            suggestion_region = user_input.get(CONF_REGION, suggestion_region)
        stations = _station_options(await _async_notices(self.hass, suggestion_region))
        # Only a new location asks for phones. Reconfigure keeps the options.
        phones = mobile_app_targets(self.hass) if step_id == "user" else None
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema(stations, defaults, phones),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the planned outages that match now, then save."""
        if user_input is not None:
            if self.source == "reconfigure":
                return await self._async_save_reconfigure()
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=self._options
            )
        notices = [
            notice
            for notice in await _async_notices(self.hass, self._data[CONF_REGION])
            if matches(self._data[CONF_STATION], notice)
        ]
        if notices:
            text = "\n".join(
                f"- {_escape_markdown(' / '.join(notice.date_texts))}: "
                f"{_escape_markdown(notice.station_text or '')} "
                f"({REGIONS[notice.region]})"
                for notice in notices
            )
        else:
            text = await self._async_no_match_text()
        return self.async_show_form(
            step_id="confirm", description_placeholders={"matches": text}
        )

    async def _async_no_match_text(self) -> str:
        key = f"component.{DOMAIN}.exceptions.no_planned_outage.message"
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "exceptions", [DOMAIN]
        )
        return translations.get(key, NO_MATCH_TEXT)

    async def _async_save_reconfigure(self) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        unique_id = unique_id_for(self._data[CONF_REGION], self._data[CONF_STATION])
        if unique_id == entry.unique_id:
            # Same region and station: keep the alert state and only reload.
            self.hass.config_entries.async_update_entry(
                entry, title=self._data[CONF_NAME], data=self._data
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")
        # Unload first. If the unload fails, the entry and its Store stay as
        # they were. The old records belong to the old station: drop them while
        # the entry is unloaded, so the new setup cannot report them as removed.
        if not await self.hass.config_entries.async_unload(entry.entry_id):
            return self.async_abort(reason="unload_failed")
        self.hass.config_entries.async_update_entry(
            entry,
            title=self._data[CONF_NAME],
            data=self._data,
            unique_id=unique_id,
        )
        await async_clear_alert_state(self.hass, entry.entry_id)
        await self.hass.config_entries.async_setup(entry.entry_id)
        return self.async_abort(reason="reconfigure_successful")


class ElektroCeljeOptionsFlow(OptionsFlow):
    """Change the phones, the reminder time and the quiet hours."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the notification options."""
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if k != SECTION_ADVANCED}
            data[CONF_NOTIFY_TARGETS] = list(data.get(CONF_NOTIFY_TARGETS, []))
            entity = (user_input.get(SECTION_ADVANCED) or {}).get(CONF_QUIET_ENTITY)
            if entity:
                data[CONF_QUIET_ENTITY] = entity
            return self.async_create_entry(data=data)
        options = self.config_entry.options
        settings = NotifySettings.from_options(options)
        phones = mobile_app_targets(self.hass)
        # Keep a stored phone in the list, so the user can see and remove it.
        for name in settings.targets:
            phones.setdefault(name, name)
        reminder = options.get(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME.isoformat())
        schema: dict[Any, Any] = {
            **_phones_field(phones, list(settings.targets)),
            vol.Required(CONF_REMINDER_TIME, default=reminder): TimeSelector(),
            vol.Required(
                CONF_QUIET_HOURS, default=settings.quiet_hours
            ): BooleanSelector(),
            vol.Required(
                CONF_QUIET_FROM, default=settings.quiet_from.isoformat()
            ): TimeSelector(),
            vol.Required(
                CONF_QUIET_TO, default=settings.quiet_to.isoformat()
            ): TimeSelector(),
            vol.Required(SECTION_ADVANCED, default={}): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_QUIET_ENTITY,
                            description={"suggested_value": settings.quiet_entity},
                        ): EntitySelector(
                            EntitySelectorConfig(domain=QUIET_ENTITY_DOMAINS)
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
