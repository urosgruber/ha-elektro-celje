"""Calendar of the planned outages."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroCeljeConfigEntry
from .const import TZ
from .entity import ElektroCeljeEntity
from .models import Outage

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroCeljeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar of one location."""
    async_add_entities([OutageCalendar(entry.runtime_data, entry, "planned_outages")])


def _event(outage: Outage) -> CalendarEvent | None:
    """Return the calendar event of an outage, or None if it has no start."""
    if outage.start is None or outage.end is None:
        return None
    start: datetime | date = outage.start
    end: datetime | date = outage.end
    if outage.all_day:
        start = outage.start.astimezone(TZ).date()
        end = max(outage.end.astimezone(TZ).date(), start + timedelta(days=1))
    description = outage.text
    if outage.link:
        description = f"{description}\n{outage.link}"
    return CalendarEvent(
        start=start,
        end=end,
        summary=f"Izklop elektrike: {outage.station_text or ''}".rstrip(": "),
        description=description,
        uid=outage.key,
    )


def _bounds(event: CalendarEvent) -> tuple[datetime, datetime]:
    start, end = event.start, event.end
    if not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time(), tzinfo=TZ)
    if not isinstance(end, datetime):
        end = datetime.combine(end, datetime.min.time(), tzinfo=TZ)
    return start, end


class OutageCalendar(ElektroCeljeEntity, CalendarEntity):
    """One event for each listed or kept outage that has a start.

    Outages that ended stay in the calendar while the feed lists them.
    """

    def _events(self) -> list[CalendarEvent]:
        listed = {o.key for o in self.data.outages}
        kept = [o for o in self.data.planned if o.key not in listed]
        events = (_event(o) for o in [*self.data.outages, *kept])
        return [e for e in events if e is not None]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current event, or the next one."""
        now = dt_util.utcnow()
        upcoming = [e for e in self._events() if _bounds(e)[1] > now]
        return min(upcoming, key=lambda e: _bounds(e)[0], default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the events that overlap the range."""
        result = []
        for event in self._events():
            start, end = _bounds(event)
            if start < end_date and end > start_date:
                result.append(event)
        return result
