"""Match a location to the station names of a notice."""

from __future__ import annotations

from .models import Notice
from .parser import normalize


def matches(query: str, notice: Notice) -> bool:
    """Return True if the query equals one station name of the notice."""
    wanted = normalize(query)
    return any(normalize(name) == wanted for name in notice.station_names)
