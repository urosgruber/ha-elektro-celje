"""Constants for the Elektro Celje integration."""

from datetime import time, timedelta
from zoneinfo import ZoneInfo

DOMAIN = "elektro_celje"

REGIONS: dict[str, str] = {
    "celje": "Celje",
    "velenje": "Velenje",
    "krsko": "Krško",
    "slovenj-gradec": "Slovenj Gradec",
}
ALL_REGIONS = "all"

FEED_URL = "https://www.elektro-celje.si/si/rss.ashx?k={region}"
SCAN_INTERVAL = timedelta(minutes=15)
TZ = ZoneInfo("Europe/Ljubljana")
DEFAULT_REMINDER_TIME = time(18, 0)

EVENT_OUTAGE_DETECTED = "elektro_celje_outage_detected"
EVENT_OUTAGE_REMINDER = "elektro_celje_outage_reminder"
EVENT_OUTAGE_CHANGED = "elektro_celje_outage_changed"
EVENT_OUTAGE_REMOVED = "elektro_celje_outage_removed"

CONF_STATION = "station"
CONF_REGION = "region"
CONF_REMINDER_TIME = "reminder_time"
