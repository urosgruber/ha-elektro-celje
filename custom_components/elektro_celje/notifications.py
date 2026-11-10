"""Built-in mobile notifications: texts, quiet hours, hold queue and sending.

The texts are a port of the built-in texts of the blueprint
`blueprints/automation/elektro_celje/outage_notify.yaml`. Feed text is plain
text here: nothing in this module renders a template.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    ALERT_KINDS,
    CONF_NOTIFY_TARGETS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_FROM,
    CONF_QUIET_HOURS,
    CONF_QUIET_TO,
    DEFAULT_QUIET_FROM,
    DEFAULT_QUIET_HOURS,
    DEFAULT_QUIET_TO,
    MOBILE_APP_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

NOTIFY_DOMAIN = "notify"

TITLES: dict[str, dict[str, str]] = {
    "sl": {
        "detected": "Načrtovan izklop",
        "reminder": "Jutri izklop",
        "changed": "Izklop spremenjen",
        "removed": "Izklop ni več objavljen",
    },
    "en": {
        "detected": "Planned power outage",
        "reminder": "Power outage tomorrow",
        "changed": "Power outage changed",
        "removed": "Power outage no longer listed",
    },
}
_WORDS: dict[str, dict[str, str]] = {
    "sl": {
        "unknown": "čas ni znan",
        "all_day": "ves dan",
        "previously": "prej",
        "now": "zdaj",
    },
    "en": {
        "unknown": "time unknown",
        "all_day": "all day",
        "previously": "previously",
        "now": "now",
    },
}
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]  # fmt: skip
_SPACE_RE = re.compile(r"\s+")
# The blueprint treats an old interval as all day when it starts at 00:00 and
# lasts at least 23 hours.
_WHOLE_DAY_SECONDS = 82800


# --- Texts ------------------------------------------------------------------


def language(hass: HomeAssistant) -> str:
    """Return "sl" when Home Assistant speaks Slovenian, else "en"."""
    return "sl" if (hass.config.language or "").lower().startswith("sl") else "en"


def _parse(value: str | None) -> datetime | None:
    return dt_util.as_local(datetime.fromisoformat(value)) if value else None


def _day(moment: datetime, lang: str) -> str:
    if lang == "en":
        return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"
    return f"{moment.day}. {moment.month}. {moment.year}"


def _when(
    start: datetime | None, end: datetime | None, all_day: bool, lang: str
) -> str:
    words = _WORDS[lang]
    if start is None:
        return words["unknown"]
    if all_day:
        clock = words["all_day"]
    else:
        clock = start.strftime("%H:%M") + (f"–{end.strftime('%H:%M')}" if end else "")
    return f"{_day(start, lang)}, {clock}"


def _old_when(payload: Mapping[str, Any], lang: str) -> str:
    if "old_start" not in payload:
        return ""
    start = _parse(payload["old_start"])
    if start is None:
        return _WORDS[lang]["unknown"]
    end = _parse(payload.get("old_end"))
    whole_day = (
        end is not None
        and start.strftime("%H:%M") == "00:00"
        and (end - start).total_seconds() >= _WHOLE_DAY_SECONDS
    )
    return _when(start, end, whole_day, lang)


def _duration(minutes: int | None) -> str:
    if minutes is None:
        return ""
    hours, rest = divmod(int(minutes), 60)
    parts = [f"{hours} h" if hours else "", f"{rest} min" if rest else ""]
    return " ".join(p for p in parts if p)


def build_texts(kind: str, payload: Mapping[str, Any], lang: str) -> tuple[str, str]:
    """Return the title and the message of an alert, as the blueprint builds them.

    `payload` is the event data of the alert.
    """
    words = _WORDS[lang]
    start = _parse(payload.get("start"))
    when = _when(start, _parse(payload.get("end")), bool(payload.get("all_day")), lang)
    old_when = _old_when(payload, lang)
    duration = _duration(payload.get("duration_minutes"))
    message = f"{payload.get('location') or ''}:"
    if old_when:
        message += f" {words['previously']} {old_when}, {words['now']}"
    message += f" {when}"
    if duration:
        message += f" ({duration})"
    text = payload.get("text")
    if start is None and text:
        message += f". {text}"
    message = _SPACE_RE.sub(" ", message).strip()
    return TITLES[lang][kind], message


def tag(entry_id: str, key: str) -> str:
    """Return the notification tag. A later alert of one outage replaces it."""
    return f"elektro_celje_{entry_id}_{key}"


# --- Settings ---------------------------------------------------------------


def _time(value: Any, default: time) -> time:
    if not value:
        return default
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        _LOGGER.warning("Invalid quiet hours time %r, using the default", value)
        return default


@dataclass(frozen=True)
class NotifySettings:
    """The notification options of one location."""

    targets: tuple[str, ...]
    quiet_hours: bool
    quiet_from: time
    quiet_to: time
    quiet_entity: str | None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> NotifySettings:
        """Read the options. A missing key gets its default."""
        return cls(
            targets=tuple(options.get(CONF_NOTIFY_TARGETS) or ()),
            quiet_hours=bool(options.get(CONF_QUIET_HOURS, DEFAULT_QUIET_HOURS)),
            quiet_from=_time(options.get(CONF_QUIET_FROM), DEFAULT_QUIET_FROM),
            quiet_to=_time(options.get(CONF_QUIET_TO), DEFAULT_QUIET_TO),
            quiet_entity=options.get(CONF_QUIET_ENTITY) or None,
        )


def quiet_window_end(now: datetime, start: time, end: time) -> datetime | None:
    """Return the end of the quiet period that contains `now`, or None.

    The times are local times of Home Assistant. A range with start > end runs
    over midnight. A range with start == end is never quiet.
    """
    if start == end:
        return None
    local = dt_util.as_local(now)
    today = local.date()
    clock = local.time().replace(tzinfo=None)
    if start < end:
        if start <= clock < end:
            return _local_end(today, end, now)
        return None
    if clock >= start:
        return _local_end(today + timedelta(days=1), end, now)
    if clock < end:
        return _local_end(today, end, now)
    return None


def _local_end(day: date, end: time, now: datetime) -> datetime:
    """Return `end` on `day` as a UTC moment after `now` when one exists.

    On the autumn DST day, a local time can occur twice. datetime.combine
    picks the first one (fold=0). If that is not after `now`, the second one
    (fold=1) is the end of the current quiet period.
    """
    tz = dt_util.get_default_time_zone()
    moment = dt_util.as_utc(datetime.combine(day, end, tzinfo=tz))
    if moment <= dt_util.as_utc(now):
        later = datetime.combine(day, end, tzinfo=tz).replace(fold=1)
        moment = dt_util.as_utc(later)
    return moment


@dataclass(frozen=True)
class QuietState:
    """Whether notifications wait now, and until when if known."""

    quiet: bool
    end: datetime | None = None


def quiet_state(
    hass: HomeAssistant, settings: NotifySettings, now: datetime
) -> QuietState:
    """Return the quiet state now.

    With an entity, it is quiet while the entity state is "on". A schedule
    gives the end in its `next_event` attribute. Other entities give no end.
    """
    if not settings.quiet_hours:
        return QuietState(False)
    if settings.quiet_entity:
        state = hass.states.get(settings.quiet_entity)
        if state is None or state.state != "on":
            return QuietState(False)
        end = state.attributes.get("next_event")
        if isinstance(end, str):
            try:
                end = datetime.fromisoformat(end)
            except ValueError:
                end = None
        return QuietState(True, end if isinstance(end, datetime) else None)
    end = quiet_window_end(now, settings.quiet_from, settings.quiet_to)
    return QuietState(end is not None, end)


# --- Hold queue -------------------------------------------------------------


def make_item(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe queue item."""
    return {"kind": kind, "payload": dict(payload)}


def merge(held: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any] | None:
    """Combine a held alert with a later alert of the same outage.

    - detected, then removed: the user never heard of it. Drop both.
    - detected, then changed: send one "detected" with the new time.
    - changed, then changed: keep the time the user saw last as the old time.
    - otherwise the later alert replaces the held one.
    """
    if held is None:
        return new
    if held["kind"] == "detected":
        if new["kind"] == "removed":
            return None
        if new["kind"] == "changed":
            payload = {
                k: v
                for k, v in new["payload"].items()
                if k not in ("old_start", "old_end")
            }
            return make_item("detected", payload)
    if held["kind"] == "changed" and new["kind"] == "changed":
        payload = dict(new["payload"])
        payload["old_start"] = held["payload"].get("old_start")
        payload["old_end"] = held["payload"].get("old_end")
        return make_item("changed", payload)
    return new


def starts_before(item: Mapping[str, Any], moment: datetime | None) -> bool:
    """Return True if the outage of the item starts before `moment`.

    An unknown start or an unknown moment gives False: the alert waits.
    """
    start = item["payload"].get("start")
    if moment is None or not start:
        return False
    return datetime.fromisoformat(start) < moment


def has_ended(item: Mapping[str, Any], now: datetime) -> bool:
    """Return True if the outage of the item ended before `now`."""
    end = item["payload"].get("end")
    return bool(end) and datetime.fromisoformat(end) <= now


def valid_item(item: Any) -> bool:
    """Return True for a stored queue item that the code can use."""
    return (
        isinstance(item, dict)
        and item.get("kind") in ALERT_KINDS
        and isinstance(item.get("payload"), dict)
    )


# --- Phones and sending -----------------------------------------------------


def mobile_app_targets(hass: HomeAssistant) -> dict[str, str]:
    """Return the mobile app notify actions, as {service name: label}.

    The label is the name of the phone device when it is known.
    """
    services = sorted(
        name
        for name in hass.services.async_services_for_domain(NOTIFY_DOMAIN)
        if name.startswith(MOBILE_APP_PREFIX)
    )
    labels: dict[str, str] = {}
    registry = dr.async_get(hass)
    for entry in hass.config_entries.async_entries("mobile_app"):
        device_name = entry.data.get("device_name")
        if not device_name:
            continue
        label = device_name
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            label = device.name_by_user or device.name or device_name
            break
        labels[f"{MOBILE_APP_PREFIX}{slugify(device_name)}"] = label
    return {name: labels.get(name, name) for name in services}


async def async_send(
    hass: HomeAssistant,
    targets: tuple[str, ...] | list[str],
    entry_id: str,
    item: Mapping[str, Any],
) -> None:
    """Send one alert to each phone. A failed phone does not stop the others."""
    payload = item["payload"]
    title, message = build_texts(item["kind"], payload, language(hass))
    data = {
        "title": title,
        "message": message,
        "data": {"tag": tag(entry_id, str(payload.get("key")))},
    }
    for target in targets:
        try:
            await hass.services.async_call(
                NOTIFY_DOMAIN, target, dict(data), blocking=True
            )
        except Exception as err:  # noqa: BLE001 - one phone must not stop the others
            _LOGGER.warning(
                "Could not send the outage notification to notify.%s: %s",
                target,
                err,
            )
