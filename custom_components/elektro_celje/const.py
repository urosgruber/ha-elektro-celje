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
PROBLEM_AFTER_SECONDS = 3600  # The card shows a feed problem after one hour.

EVENT_OUTAGE_DETECTED = "elektro_celje_outage_detected"
EVENT_OUTAGE_REMINDER = "elektro_celje_outage_reminder"
EVENT_OUTAGE_CHANGED = "elektro_celje_outage_changed"
EVENT_OUTAGE_REMOVED = "elektro_celje_outage_removed"

CONF_STATION = "station"
CONF_REGION = "region"
CONF_REMINDER_TIME = "reminder_time"

# Built-in notifications (2.3.0). All keys live in entry.options.
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_QUIET_HOURS = "quiet_hours"
CONF_QUIET_FROM = "quiet_from"
CONF_QUIET_TO = "quiet_to"
CONF_QUIET_ENTITY = "quiet_entity"
SECTION_ADVANCED = "advanced"
DEFAULT_QUIET_HOURS = True
DEFAULT_QUIET_FROM = time(22, 0)
DEFAULT_QUIET_TO = time(7, 0)
QUIET_ENTITY_DOMAINS = ["schedule", "input_boolean", "binary_sensor"]
MOBILE_APP_PREFIX = "mobile_app_"
ALERT_KINDS = ("detected", "reminder", "changed", "removed")
