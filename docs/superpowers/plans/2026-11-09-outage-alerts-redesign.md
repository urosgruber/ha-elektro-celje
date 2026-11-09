# Elektro Celje Planned Outages 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the YAML-only binary sensor with a UI-configured integration that lists every planned outage per location, fires alert events, and is ready for a HACS custom-repository release (stage 1).

**Architecture:** Pure modules (`parser`, `matching`, `outages`, `alerts`) hold all feed and alert logic and are tested without HA. One shared `RegionCoordinator` per feed downloads and parses. One `LocationCoordinator` per config entry combines its region coordinators, keeps alert state in an HA `Store`, fires events and drives the entities. A blueprint and a copy-and-paste card live in the repository.

**Tech Stack:** Python 3.13, Home Assistant custom integration APIs (`DataUpdateCoordinator`, config flow, `Store`, calendar, diagnostics, issue registry), stdlib `xml.etree` and `html.parser` (no third-party requirements), `pytest-homeassistant-custom-component`, Ruff, `uv`.

**Spec:** `docs/superpowers/specs/2026-11-09-outage-alerts-redesign-design.md`

## Global Constraints

- Domain stays `elektro_celje`. Version becomes `2.0.0`.
- Feed URL: `https://www.elektro-celje.si/si/rss.ashx?k=<slug>`. Slugs: `celje`, `velenje`, `krsko`, `slovenj-gradec`. Labels: Celje, Velenje, Krško, Slovenj Gradec. Extra option "All regions" (value `all`), the default.
- Time zone for all dates: `Europe/Ljubljana`. All datetimes are timezone-aware.
- Poll interval: 15 minutes, one download per region feed, shared by all locations.
- Default reminder time: 18:00 on the day before the outage.
- Event types: `elektro_celje_outage_detected`, `elektro_celje_outage_reminder`, `elektro_celje_outage_changed`, `elektro_celje_outage_removed`.
- Removal wording is "no longer listed", never "cancelled".
- A fetch or format error is a failure, never an empty result. No `removed` event for a region whose last fetch failed.
- No third-party `requirements` in the manifest. Do not use `feedparser` or BeautifulSoup.
- Matching is exact per station name (spec §7.3). Owner queries that must keep working: `zabukovica papež` (velenje), `lopata oberžan` (celje).
- User-facing text exists in English and Slovenian.
- Large attributes go into `_unrecorded_attributes`. Diagnostics redact the location name and the station query.

## Review Focus

1. **An end time before the start time** ("med 22:00 in 02:00"): the end moves to the next day. Test in Task 1.
2. **A date line with two dates or a range** ("od 9. do 11. novembra 2026"): status `failed`, never a wrong single date. Test in Task 1.
3. **HTTP 200 with a non-RSS body** (HTML error page, truncated XML): a failure, not an empty feed. Test in Task 4.
4. **HA restarts while the feed is down:** stored outages stay planned and no `removed` event fires. Test in Task 6.
5. **The user changes the station with reconfigure:** the old alert state is cleared without `removed` events for the old station. Test in Task 7.

---

## File structure

```
custom_components/elektro_celje/
  __init__.py        setup/unload of a config entry, shared region registry
  const.py           constants from Global Constraints
  models.py          Notice, Interval, Outage, ParseStatus
  parser.py          XML -> Notice list; date/time parsing; station split; normalize
  matching.py        query vs Notice
  client.py          HTTP download with timeout, size limit, User-Agent
  coordinator.py     RegionCoordinator + shared registry helpers
  outages.py         Outage list, planned/active/countdown/reminder/boundary math
  alerts.py          OutageRecord, AlertEvent, evaluate(), event payloads
  location.py        LocationCoordinator: store, events, time scheduling
  entity.py          base entity + DeviceInfo
  sensor.py, binary_sensor.py, calendar.py
  config_flow.py     user, confirm (preview), reconfigure, options, import
  diagnostics.py
  manifest.json, strings.json, translations/en.json, translations/sl.json
blueprints/automation/elektro_celje/outage_notify.yaml
docs/dashboard-card.yaml
tests/ (conftest.py, test_*.py, fixtures/)
pyproject.toml, requirements_test.txt, hacs.json, README.md, .github/workflows/
```

Delete `custom_components/elektro_celje/elektro_celje_parser.py`. `binary_sensor.py` is rewritten.

---

### Task 1: Tooling, models and the feed parser

**Files:**
- Create: `pyproject.toml`, `requirements_test.txt`, `tests/conftest.py`, `custom_components/elektro_celje/const.py`, `custom_components/elektro_celje/models.py`, `custom_components/elektro_celje/parser.py`, `tests/fixtures/expected_2026-11-09.json`, `tests/test_parser.py`
- Delete: `custom_components/elektro_celje/elektro_celje_parser.py`

**Interfaces:**
- Produces (`models.py`):
  - `class ParseStatus(StrEnum)`: `OK = "ok"`, `DATE_ONLY = "date_only"`, `FAILED = "failed"`
  - `@dataclass(frozen=True) Interval(start: datetime, end: datetime, all_day: bool = False)`
  - `@dataclass(frozen=True) Notice(notice_id: str, region: str, title: str, link: str, station_text: str | None, station_names: tuple[str, ...], text: str, date_texts: tuple[str, ...], intervals: tuple[Interval, ...], status: ParseStatus, reason: str | None)`
- Produces (`parser.py`):
  - `class FeedFormatError(Exception)`
  - `parse_feed(xml_text: str, region: str) -> list[Notice]` — raises `FeedFormatError` when the root is not `<rss>` with a `<channel>`.
  - `parse_schedule(line: str) -> tuple[ParseStatus, Interval | None, str | None]` — one `<li>` text.
  - `split_station_names(station_text: str) -> tuple[str, ...]` (Task 3 fills the rules; Task 1 returns `(station_text,)`).
  - `normalize(text: str) -> str`
  - `notice_id_from(link: str, region: str, station_text: str | None, date_text: str) -> str`
- Produces (`const.py`): `DOMAIN`, `REGIONS: dict[str, str]` (slug → label), `ALL_REGIONS = "all"`, `FEED_URL`, `SCAN_INTERVAL = timedelta(minutes=15)`, `TZ = ZoneInfo("Europe/Ljubljana")`, `DEFAULT_REMINDER_TIME = time(18, 0)`, the four `EVENT_*` names, `CONF_STATION = "station"`, `CONF_REGION = "region"`, `CONF_REMINDER_TIME = "reminder_time"`.

- [ ] **Step 1: Set up the environment**

`requirements_test.txt`: `pytest-homeassistant-custom-component` (latest release, pinned with `==`), `ruff`. `pyproject.toml`: Ruff config (target `py313`), pytest `asyncio_mode = "auto"`, `testpaths = ["tests"]`. `tests/conftest.py`: an autouse fixture that uses `enable_custom_integrations`.

Run: `uv venv --python 3.13 .venv && uv pip install -r requirements_test.txt`
Expected: install succeeds.

- [ ] **Step 2: Write the expected values for the 51 fixture items**

Create `tests/fixtures/expected_2026-11-09.json`: a list with one object per `<item>` in the four fixture files: `{"file", "notice_id", "status", "start", "end"}` (ISO strings with `+01:00`, or `null`). Read the start and end from each `<li>` text by eye. A throwaway script may draft the file, but check every row against the fixture text before you commit. Example rows:

```json
{"file": "rss_velenje_2026-11-09.xml", "notice_id": "43322", "status": "ok",
 "start": "2026-11-09T08:30:00+01:00", "end": "2026-11-09T11:00:00+01:00"}
{"file": "rss_celje_2026-11-09.xml", "notice_id": "<id from link>", "status": "ok",
 "start": "2026-11-09T08:00:00+01:00", "end": "2026-11-09T11:00:00+01:00"}
```

The second row is the Zvodno item with `09.november 2026`. Take the real numeric IDs from the `link` values.

- [ ] **Step 3: Write the failing tests**

```python
@pytest.mark.parametrize("row", EXPECTED, ids=lambda r: f'{r["file"]}:{r["notice_id"]}')
def test_fixture_items_parse_exactly(row):
    notices = {n.notice_id: n for n in parse_feed(read(row["file"]), region_of(row["file"]))}
    n = notices[row["notice_id"]]
    assert n.status == row["status"]
    assert n.intervals[0].start.isoformat() == row["start"]
    assert n.intervals[0].end.isoformat() == row["end"]

def test_fixture_item_count():
    assert sum(len(parse_feed(read(f), region_of(f))) for f in FILES) == 51

@pytest.mark.parametrize("line,start,end", [
    ("v ponedeljek, 09. novembra 2026, predvidoma med 08:30 in 11:30 uro", "08:30", "11:30"),
    ("v torek, 10. novembra 2026, predvidoma med 8:00 in 13:00 uro", "08:00", "13:00"),
    ("v ponedeljek, 9. novembra 2026, predvidoma med 8:00 in 14:00 uro", "08:00", "14:00"),
    ("v ponedeljek, 09. novembra 2026, predvidoma med 08.30 in 11.00 uro", "08:30", "11:00"),
    ("v ponedeljek, 09.november 2026, predvidoma med 08:00 in 11:00 uro", "08:00", "11:00"),
    ("v ponedeljek, 9. november 2026, predvidoma med 9:00 in 13:30 uro", "09:00", "13:30"),
    ("v sredo, 11. november 2026, predvidoma med 8:00 in 8:30 uro", "08:00", "08:30"),
])
def test_time_formats(line, start, end): ...  # status OK, local HH:MM equal

def test_all_month_forms():
    # januar/januarja, februar/februarja, marec/marca, april/aprila, maj/maja, junij/junija,
    # julij/julija, avgust/avgusta, september/septembra, oktober/oktobra, november/novembra,
    # december/decembra -> months 1..12
    ...

def test_end_before_start_moves_to_next_day():          # Review Focus 1
    s, iv, _ = parse_schedule("v petek, 13. novembra 2026, predvidoma med 22:00 in 02:00 uro")
    assert s is ParseStatus.OK and iv.end == datetime(2026, 11, 14, 2, 0, tzinfo=TZ)

def test_two_dates_in_one_line_fail():                   # Review Focus 2
    s, iv, reason = parse_schedule("od 9. do 11. novembra 2026, med 8:00 in 14:00 uro")
    assert s is ParseStatus.FAILED and iv is None and reason

def test_date_without_times_is_date_only():
    s, iv, _ = parse_schedule("v torek, 10. novembra 2026, ves dan")
    assert s is ParseStatus.DATE_ONLY and iv.all_day
    assert iv.start == datetime(2026, 11, 10, tzinfo=TZ) and iv.end == datetime(2026, 11, 11, tzinfo=TZ)

def test_unreadable_line_fails(): ...                    # "po dogovoru" -> FAILED, reason set
def test_multiple_li_give_multiple_intervals(): ...      # synthetic item with 2 <li>
def test_notice_status_is_worst_of_its_lines(): ...      # one OK li + one FAILED li -> FAILED
def test_dst_dates_are_aware(): ...                      # 29. marca 2026 med 02:30 in 04:00 -> valid aware datetimes
def test_not_rss_raises():
    with pytest.raises(FeedFormatError): parse_feed("<html><body>Error</body></html>", "celje")
def test_empty_channel_returns_empty_list(): ...
def test_notice_id_uses_numeric_link_id():
    assert notice_id_from("https://www.elektro-celje.si:443/si/aktualno/obvestila-o-izklopih/celje/2026/11/43309-993-Nadzornistvo", "celje", "Repno", "x") == "43309"
def test_notice_id_without_number_is_stable_hash(): ...  # same input -> same id; different region -> different id
def test_normalize(): assert normalize("  Zabukovica   PAPEŽ ") == "zabukovica papez"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parser.py -q`
Expected: FAIL (import errors).

- [ ] **Step 5: Implement `const.py`, `models.py` and `parser.py`**

Parsing rules:
- Reject input over 1 MB in `parse_feed`, before XML parsing (`FeedFormatError`).
- Description: `html.unescape`, then extract with `html.parser.HTMLParser`: the first `<strong>` text (station text), the text of each `<li>` inside `ul.dates-list`, and the whole plain text (whitespace collapsed).
- Date: one match of `(\d{1,2})\.\s*([a-zčšž]+)\s+(\d{4})` (case-insensitive). Map the month by its first three letters: `jan feb mar apr maj jun jul avg sep okt nov dec`. More than one day-number token before the year (as in "od 9. do 11.") → `FAILED`.
- Times: `med\s+(\d{1,2})[:.](\d{2})\s+in\s+(\d{1,2})[:.](\d{2})`. If missing, take the first two `\d{1,2}[:.]\d{2}` tokens after the date. No times → `DATE_ONLY`.
- Build datetimes with `tzinfo=TZ`. If end ≤ start, add one day to the end.
- `normalize`: `unicodedata.normalize("NFKD")`, drop combining marks, `casefold()`, collapse whitespace, strip.
- `notice_id_from`: the first `/(\d+)-` in the link path; otherwise the first 12 hex digits of `sha256(region|station_text|date_text)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parser.py -q && .venv/bin/ruff check .`
Expected: all pass, Ruff clean.

- [ ] **Step 7: Commit**

`git add -A && git commit -m "feat: parse every date and time format in the outage feed"`

---

### Task 2: Station names and matching

**Files:**
- Modify: `custom_components/elektro_celje/parser.py` (`split_station_names`)
- Create: `custom_components/elektro_celje/matching.py`, `tests/test_matching.py`

**Interfaces:**
- Consumes: `Notice`, `normalize` from Task 1.
- Produces: `split_station_names(station_text: str) -> tuple[str, ...]`; `matches(query: str, notice: Notice) -> bool`.

- [ ] **Step 1: Write the failing tests**

Copy both tables of spec §7.3 as parametrized cases:

```python
@pytest.mark.parametrize("text,names", [
    ("Zabukovica Papež - nizkonapetostni izvod Kozovinc", ("Zabukovica Papež",)),
    ("Babna Reka in Baberšica", ("Babna Reka", "Baberšica")),
    ("Žegar, nizkonapetostno omrežje - Vodovod", ("Žegar",)),
    ("Mokronog nadzorništvo, nizkonapetostno omrežje – Puščava vas", ("Mokronog nadzorništvo",)),
    ("Podgorje Vravar - izvod Podgorje 103, 104 in 104a", ("Podgorje Vravar",)),
    ("Impolje, Orle, Prlska gora, Zavratec ribnik, Dedna gora in Studenec Matko",
     ("Impolje", "Orle", "Prlska gora", "Zavratec ribnik", "Dedna gora", "Studenec Matko")),
    ("Stanovanjske hiše Kotlje od št.88 do št.97", ("Stanovanjske hiše Kotlje od št.88 do št.97",)),
])
def test_split_station_names(text, names): assert split_station_names(text) == names

@pytest.mark.parametrize("query,station_text,expected", [
    ("zabukovica papež", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", True),
    ("zabukovica", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", False),
    ("žusem", "Spodnji Žusem", False),
    ("žusem", "Glažuta, Aero Loka, Loka pri Žusmu, Žusem, Dobrina", True),
    ("studenec", "Studenec", True),
    ("studenec", "Impolje, Orle, Dedna gora in Studenec Matko", False),
    ("Zabukovica Papez", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", True),
])
def test_matches(query, station_text, expected): ...

def test_no_station_text_never_matches(): ...      # Notice(station_text=None) -> False
def test_every_fixture_notice_has_names(): ...      # all 51 notices: station_names non-empty, no name starts with "nizkonapetostn"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_matching.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement**

`split_station_names`: cut at the first ` - `, ` – `, or at the first comma-separated part that starts with `nizkonapetostn` or `izvod` (case-insensitive); split the rest on `,` and on the whole word ` in `; trim; drop empties. `parse_feed` fills `Notice.station_names` with it. `matches`: `normalize(query)` equals `normalize(name)` for any name.

- [ ] **Step 4: Run the tests** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: match a location to exactly one station name"`

---

### Task 3: Outage math

**Files:**
- Create: `custom_components/elektro_celje/outages.py`, `tests/test_outages.py`
- Modify: `custom_components/elektro_celje/models.py` (add `Outage`)

**Interfaces:**
- Consumes: `Notice`, `Interval`, `ParseStatus`, `matches`.
- Produces:
  - `@dataclass(frozen=True) Outage(key: str, notice_id: str, region: str, station_text: str | None, text: str, link: str, status: ParseStatus, start: datetime | None, end: datetime | None, all_day: bool)` — `key = f"{notice_id}:{index}"`; a `FAILED` notice gives one outage with `start = end = None`, key `f"{notice_id}:0"`.
  - `build_outages(notices: Iterable[Notice], query: str) -> list[Outage]` — sorted by start, `None` last.
  - `is_planned(o: Outage, now: datetime) -> bool` — `FAILED` → True; else `o.end > now`.
  - `is_active(o: Outage, now: datetime) -> bool` — only status `OK`: `start <= now < end`.
  - `days_until(o: Outage, now: datetime) -> int | None` — local-date difference in `TZ`, minimum 0; `None` for `FAILED`.
  - `reminder_at(o: Outage, reminder: time) -> datetime | None` — the local date before `o.start`, at `reminder`, in `TZ`; `None` for `FAILED`.
  - `next_boundary(outages: list[Outage], now: datetime, reminder: time) -> datetime` — the earliest future value among starts, ends, reminder moments and the next local midnight.

- [ ] **Step 1: Write the failing tests**

```python
def test_planned_until_end(): ...            # ok outage 08:30–11:00: planned at 10:59, not at 11:00
def test_failed_always_planned(): ...
def test_date_only_planned_until_midnight(): ...
def test_active_only_for_ok(): ...           # date_only outage today -> is_active False
def test_days_until_counts_local_dates():
    o = outage(start="2026-11-10T08:30+01:00", end="2026-11-10T11:00+01:00")
    assert days_until(o, at("2026-11-09T23:59+01:00")) == 1
    assert days_until(o, at("2026-11-10T00:00+01:00")) == 0
    assert days_until(o, at("2026-11-10T09:00+01:00")) == 0
def test_days_until_across_dst(): ...        # now 2027-03-27 12:00, start 2027-03-29 08:00 -> 2
def test_reminder_at_day_before(): assert reminder_at(o, time(18)) == at("2026-11-09T18:00+01:00")
def test_next_boundary_picks_earliest(): ...  # cases: next start, next end, reminder, midnight
def test_build_outages_two_li_two_outages(): ...  # keys "<id>:0", "<id>:1"
def test_build_outages_filters_by_query(): ...
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_outages.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement `outages.py` and `Outage`.**
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: compute planned, active and countdown state per outage"`

---

### Task 4: Download and region coordinator

**Files:**
- Create: `custom_components/elektro_celje/client.py`, `custom_components/elektro_celje/coordinator.py`, `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `parse_feed`, `FeedFormatError`, constants.
- Produces:
  - `class FeedError(Exception)`; `async def async_fetch_feed(session: aiohttp.ClientSession, region: str) -> str` — timeout 30 s, body limit 1 MB, header `User-Agent: HomeAssistant-elektro_celje/2.0.0 (+https://github.com/urosgruber/ha-elektro-celje)`. Non-200, timeout, oversize and client errors raise `FeedError`.
  - `@dataclass RegionData(notices: list[Notice], fetched_at: datetime)`
  - `class RegionCoordinator(DataUpdateCoordinator[RegionData])` — `update_interval=SCAN_INTERVAL`; public `region: str`, `feed_url: str`, `last_attempt: datetime | None`, `last_success: datetime | None`, `problem_since: datetime | None`. `FeedError` and `FeedFormatError` become `UpdateFailed`; `data` keeps the last good value.
  - `async def async_acquire_region(hass: HomeAssistant, region: str) -> RegionCoordinator` — one instance per region in `hass.data[DOMAIN]["regions"]`, with a reference count; first refresh on creation.
  - `async def async_release_region(hass: HomeAssistant, region: str) -> None` — shuts the coordinator down when the count reaches 0.

- [ ] **Step 1: Write the failing tests** (use `aioclient_mock` with the fixture files)

```python
async def test_fetch_and_parse_velenje(hass, aioclient_mock): ...     # 9 notices; last_success set; problem_since None
async def test_http_error_keeps_last_data(hass, aioclient_mock, freezer): ...
    # 1st poll OK, 2nd poll 500 -> last_update_success False, data unchanged, problem_since = time of 2nd poll
async def test_non_rss_body_is_failure(hass, aioclient_mock): ...     # Review Focus 3: 200 + "<html>..." -> failure, not empty
async def test_truncated_xml_is_failure(hass, aioclient_mock): ...    # Review Focus 3
async def test_recovery_clears_problem_since(hass, aioclient_mock): ...
async def test_shared_coordinator_one_request(hass, aioclient_mock): ...  # acquire twice -> 1 HTTP call; release twice -> shut down
async def test_user_agent_header(hass, aioclient_mock): ...
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_coordinator.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** with `async_get_clientsession(hass)`. Read the body in chunks and stop at 1 MB. Set `last_attempt` before the request, `last_success` after a good parse, and `problem_since` on the first failure after a success (or on the first ever attempt).
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: download each region feed once and report failures"`

---

### Task 5: Alert evaluation

**Files:**
- Create: `custom_components/elektro_celje/alerts.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: `Outage`, `is_planned`, `reminder_at`.
- Produces:
  - `@dataclass OutageRecord(key, notice_id, region, station_text, text, link, status: ParseStatus, start: datetime | None, end: datetime | None, all_day: bool, first_seen: datetime, reminder_sent: bool)` with `to_dict() -> dict` and `@classmethod from_dict(d) -> OutageRecord`.
  - `@dataclass(frozen=True) AlertEvent(kind: Literal["detected", "reminder", "changed", "removed"], record: OutageRecord, old_start: datetime | None = None, old_end: datetime | None = None)`
  - `evaluate(records: dict[str, OutageRecord], outages: list[Outage], now: datetime, ok_regions: set[str], reminder: time) -> tuple[list[AlertEvent], dict[str, OutageRecord]]`
  - `event_type(kind: str) -> str` (maps to the `EVENT_*` constants)
  - `event_payload(event: AlertEvent, location: str, entry_id: str) -> dict[str, Any]` — keys: `location`, `entry_id`, `notice_id`, `region`, `station`, `start`, `end` (ISO or `None`), `all_day`, `duration_minutes` (`None` unless status `OK`), `status`, `text`, `link`, and for `changed` also `old_start`, `old_end`.

Rules for `evaluate` (spec §7.4, §7.7):
- New key → `detected`; `first_seen = now`. If `now >= reminder_at`, set `reminder_sent = True` without a `reminder` event (late detection).
- Same key, different `start`/`end`/`status` → `changed` with the old times; reset `reminder_sent` unless the new reminder moment is already past.
- Key missing from `outages`: if `record.region in ok_regions` and the record is not `FAILED` and `is_planned(record, now)` → `removed`, then drop it. If the region is not in `ok_regions` → keep the record unchanged. If the outage has ended → drop it silently.
- `reminder_at <= now < start` and not `reminder_sent` → `reminder`, set `reminder_sent`.
- Records that are no longer planned are dropped.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_outage_fires_detected_once(): ...          # evaluate twice with same input -> 1 event total
def test_reminder_fires_at_reminder_time(): ...         # now 17:59 -> none; now 18:00 -> reminder; 18:15 -> none
def test_late_detection_skips_reminder(): ...           # first seen 20:00 day before -> only detected, reminder_sent True
def test_changed_time_fires_changed_with_old_times(): ...
def test_changed_time_rearms_reminder(): ...
def test_removed_before_end_fires_removed(): ...
def test_removed_after_end_is_silent(): ...
def test_failed_notice_never_fires_removed(): ...
def test_date_only_removed_same_day_fires_removed(): ...
def test_no_removed_when_region_failed(): ...           # ok_regions = set() -> record kept, no event
def test_records_round_trip_through_dict(): ...
def test_payload_keys_and_duration(): ...               # 08:30–11:00 -> duration_minutes 150; changed has old_start/old_end
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_alerts.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement `alerts.py`.** `OutageRecord` has the fields of `Outage`, so `is_planned` and `reminder_at` accept it too. Use a `Protocol` or a shared base.
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: decide detected, reminder, changed and removed alerts"`

---

### Task 6: Location coordinator and integration setup

**Files:**
- Create: `custom_components/elektro_celje/location.py`, `tests/test_location.py`
- Modify: `custom_components/elektro_celje/__init__.py`, `custom_components/elektro_celje/manifest.json`

**Interfaces:**
- Consumes: `async_acquire_region`, `async_release_region`, `RegionCoordinator`, `build_outages`, `is_planned`, `next_boundary`, `evaluate`, `event_type`, `event_payload`, `OutageRecord`.
- Produces:
  - `@dataclass LocationData(outages: list[Outage], planned: list[Outage], records: dict[str, OutageRecord], feed_urls: list[str], last_attempt: datetime | None, last_success: datetime | None, problem_since: datetime | None, feed_ok: bool)` — `last_success` is the oldest `last_success` of its regions; `problem_since` the earliest of its regions; `feed_ok` is True only if all its regions succeeded.
  - `class LocationCoordinator(DataUpdateCoordinator[LocationData])` — `update_interval=None`; constructor `(hass, entry: ConfigEntry, regions: list[RegionCoordinator])`; refreshes when any region coordinator updates and at `next_boundary(...)` (via `async_track_point_in_utc_time`); stores records in `Store(hass, 1, f"elektro_celje.{entry.entry_id}")`; fires each `AlertEvent` with `hass.bus.async_fire(event_type(e.kind), event_payload(e, entry.title, entry.entry_id))`; `async_shutdown()` cancels the timer.
  - `entry.runtime_data: LocationCoordinator`
  - Config entry data keys: `name` (entry title), `CONF_REGION` (slug or `all`), `CONF_STATION`. Option `CONF_REMINDER_TIME` (`"HH:MM:SS"`, default `"18:00:00"`).
  - `PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR]`
- Manifest: `"config_flow": true`, `"integration_type": "service"`, `"iot_class": "cloud_polling"`, `"version": "2.0.0"`, `"codeowners": ["@urosgruber"]`, `"documentation"` and `"issue_tracker"` pointing at the GitHub repository, `"requirements": []`. Remove all other keys.

- [ ] **Step 1: Write the failing tests** (`MockConfigEntry`, `aioclient_mock`, `freezer`, `async_capture_events`)

```python
async def test_setup_zabukovica_detects_outage(hass, ...):     # freezer 2026-11-09 07:40; velenje fixture; query "zabukovica papež"
    # -> one elektro_celje_outage_detected event, start 08:30, end 11:00, planned list length 1
async def test_all_regions_location_uses_four_feeds(hass, ...): ...
async def test_two_locations_same_notice_fire_separately(hass, ...): ...  # two entries, one feed request per region
async def test_outage_now_flips_at_start_without_poll(hass, ...): ...     # move clock to 08:30 -> data refreshed, active
async def test_reminder_event_at_18(hass, ...): ...                        # outage on 10 Nov, clock to 9 Nov 18:00
async def test_restart_does_not_refire(hass, ...): ...                     # setup, unload, setup again -> no second detected
async def test_restart_with_feed_down_keeps_outages(hass, ...):            # Review Focus 4
    # setup with feed OK, unload; feed now returns 500; setup -> entry loads from store,
    # planned list unchanged, no removed event, feed_ok False
async def test_unload_releases_regions(hass, ...): ...
```

If the first region refresh fails and no stored records exist, setup still succeeds and `feed_ok` is False. Do not raise `ConfigEntryNotReady`: the card must show the feed problem (spec §7.8).

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_location.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement `location.py` and `__init__.py`** (`async_setup_entry`, `async_unload_entry`, and an update listener that reloads the entry when options change).
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: track outages and fire alert events per location"`

---

### Task 7: Config flow, options and translations

**Files:**
- Create: `custom_components/elektro_celje/config_flow.py`, `custom_components/elektro_celje/strings.json`, `custom_components/elektro_celje/translations/en.json`, `custom_components/elektro_celje/translations/sl.json`, `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `async_fetch_feed`, `parse_feed`, `split_station_names`, `matches`, `normalize`, constants.
- Produces: steps `user` → `confirm` → entry; `reconfigure`; options step `init`; `import` (used by Task 9). `unique_id = f"{region}:{normalize(station)}"`.

Flow details:
- `user`: `name` (text, required), `region` (`SelectSelector`, options `all` + the four slugs with translated labels, default `all`), `station` (`SelectSelector` with `custom_value=True`; options = station names in the selected feeds now, sorted; if the download fails, the options list is empty and typing still works). Empty or whitespace station → error `station_required`.
- `confirm`: no fields. `description_placeholders["matches"]` lists the matching notices now (date line + station text + region), or the translated text "No planned outage for this station now. This is normal." Submit creates the entry.
- `reconfigure`: same fields as `user`, then `confirm`; on save, clear the stored records of the entry (Review Focus 5) and reload.
- Options `init`: `reminder_time` (`TimeSelector`, default `18:00:00`).
- Duplicate `unique_id` → abort `already_configured`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_user_flow_creates_entry(hass, aioclient_mock): ...   # name "TP Zabukovica", velenje, "Zabukovica Papež" -> entry data
async def test_station_suggestions_from_feed(hass, aioclient_mock): ...  # options contain "Zabukovica Papež", "Breg Pevec"
async def test_preview_shows_match(hass, aioclient_mock): ...       # placeholder contains "08.30 in 11.00"
async def test_preview_no_match_text(hass, aioclient_mock): ...
async def test_feed_down_still_allows_typed_station(hass, aioclient_mock): ...
async def test_empty_station_rejected(hass): ...
async def test_duplicate_aborts(hass, aioclient_mock): ...
async def test_options_reminder_time(hass): ...
async def test_reconfigure_clears_alert_state(hass, aioclient_mock):   # Review Focus 5
    # entry with stored records for "zabukovica papež"; reconfigure to "breg pevec"
    # -> store has no old records; no elektro_celje_outage_removed event fired
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_config_flow.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement the flow and the three translation files.** `strings.json` and `en.json` are identical. `sl.json` has the same keys in Slovenian. The region labels are `Vse regije`, `Celje`, `Velenje`, `Krško`, `Slovenj Gradec`.
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: add locations from the UI with a live preview"`

---

### Task 8: Entities

**Files:**
- Create: `custom_components/elektro_celje/entity.py`, `custom_components/elektro_celje/sensor.py`, `custom_components/elektro_celje/calendar.py`, `tests/test_entities.py`
- Rewrite: `custom_components/elektro_celje/binary_sensor.py` (keep `async_setup_platform` as a stub that Task 9 fills)
- Modify: `strings.json`, `translations/en.json`, `translations/sl.json` (entity names)

**Interfaces:**
- Consumes: `LocationCoordinator`, `LocationData`, `is_active`, `days_until`.
- Produces entities, all with `has_entity_name = True`, `translation_key`, and `unique_id = f"{entry_id}_{key}"`. One device per entry (`identifiers={(DOMAIN, entry_id)}`, `name=entry.title`, `manufacturer="Elektro Celje"`, `entry_type=DeviceEntryType.SERVICE`).

| key | platform | value |
|---|---|---|
| `planned_outages` | sensor | `len(planned)`; attribute `outages`: list of `{start, end, all_day, status, station, region, text (max 300 chars), link}`; attributes `feed_urls`, `last_success` |
| `next_outage_start` | sensor, `TIMESTAMP` | first planned outage with a start, else `None` |
| `next_outage_end` | sensor, `TIMESTAMP` | its end |
| `days_until_outage` | sensor | `days_until` of the first planned outage; `None` when nothing is planned |
| `last_checked` | sensor, `TIMESTAMP`, diagnostic | `last_attempt` |
| `last_successful_check` | sensor, `TIMESTAMP`, diagnostic | `last_success` |
| `outage_planned` | binary_sensor | `len(planned) > 0`; same debug attributes as `planned_outages` |
| `outage_now` | binary_sensor, no device class | any `is_active` |
| `feed_problem` | binary_sensor, `PROBLEM`, diagnostic | `not feed_ok`; attribute `problem_since` |
| `planned_outages` | calendar | one `CalendarEvent` per planned outage that has a start; summary `"Izklop elektrike: <station>"` (HA does not translate event summaries, so the summary is Slovenian, like the feed); description = notice text + link; all-day for `DATE_ONLY` |

`outages`, `feed_urls` and the debug text are in `_unrecorded_attributes`. The entities do not become unavailable when the feed fails; they keep the last data (spec §7.5).

- [ ] **Step 1: Write the failing tests**

```python
async def test_entities_for_planned_outage(hass, ...): ...  # 2026-11-09 07:40, Zabukovica: planned_outages "1", days_until "0", next start 08:30
async def test_nothing_planned_states(hass, ...): ...       # days_until "unknown", next start "unknown", outage_planned off
async def test_feed_problem_entity(hass, ...): ...          # 500 -> feed_problem on, outages kept
async def test_calendar_events_in_range(hass, ...): ...     # calendar.get_events returns the 08:30–11:00 event
async def test_failed_notice_in_attribute_not_calendar(hass, ...): ...
async def test_outages_attribute_not_recorded(hass, ...): ...  # "outages" in entity._unrecorded_attributes
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_entities.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: add outage sensors, binary sensors and calendar"`

---

### Task 9: YAML import, repair issue and diagnostics

**Files:**
- Modify: `custom_components/elektro_celje/binary_sensor.py` (`async_setup_platform`), `config_flow.py` (`async_step_import`), translation files (issue text)
- Create: `custom_components/elektro_celje/diagnostics.py`, `tests/test_import_diagnostics.py`

**Interfaces:**
- Consumes: the config flow from Task 7.
- Produces: `async_setup_platform` starts an `import` flow with `{name, region, station}` from the YAML keys `name`, `region`, `search_station`, then creates the issue `deprecated_yaml` (`ir.async_create_issue`, severity `WARNING`, not fixable). Region mapping: `normalize(value)` with spaces replaced by `-`; unknown values become `all`. `async_get_config_entry_diagnostics(hass, entry) -> dict` returns entry data, options, the raw region items (title, link, description), the parsed notices, the outage list and the stored records, with `name`, `title` and `station` redacted through `async_redact_data`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_yaml_import_creates_entries(hass, ...):
    # binary_sensor YAML for both owner sensors -> 2 entries:
    # ("TP Zabukovica", "velenje", "zabukovica papež"), ("TP Lopata", "celje", "lopata oberžan"); issue deprecated_yaml exists
async def test_yaml_import_twice_is_idempotent(hass, ...): ...
async def test_yaml_region_with_accent_maps(hass, ...): ...   # "Krško" -> "krsko", "Slovenj Gradec" -> "slovenj-gradec"
async def test_diagnostics_redacts(hass, ...): ...            # "Zabukovica" and the entry title not in the JSON dump
```

- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_import_diagnostics.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: import YAML sensors and add diagnostics"`

---

### Task 10: Blueprint, card, documentation, CI and the stage 1 release

**Files:**
- Create: `blueprints/automation/elektro_celje/outage_notify.yaml`, `docs/dashboard-card.yaml`, `.github/workflows/validate.yml`, `.github/workflows/tests.yml`, `tests/test_blueprint.py`
- Modify: `README.md`, `hacs.json`

**Interfaces:**
- Consumes: the event names and payload keys from Task 5; the entity keys from Task 8.

Blueprint:
- Inputs: `notify_device` (device selector, integration `mobile_app`), four booleans `on_detected`, `on_reminder`, `on_changed`, `on_removed` (all default true), optional `locations` (text, empty = all).
- Triggers: the four events. A condition checks the boolean for `trigger.event.event_type` and the location filter.
- Action: mobile app notify with `data.tag: "elektro_celje_{{ trigger.event.data.entry_id }}_{{ trigger.event.data.notice_id }}"`. Title per kind (Slovenian): "Načrtovan izklop", "Jutri izklop", "Izklop spremenjen", "Izklop ni več objavljen". The message has the location, the date, the start–end time and the duration. A `FAILED` notice says "čas ni znan" and adds the notice text.

Card (`docs/dashboard-card.yaml`): a markdown card that renders mockup v4 (`docs/superpowers/specs/2026-11-09-dashboard-mockup-v4.html`) from `integration_entities('elektro_celje')`. It reads the `outages` attribute of each `*_planned_outages` sensor, and `problem_since` of each `*_feed_problem` binary sensor. Rules: the banner shows the active outage, else the next one; "Also planned" lists the others grouped by day; the footer shows "Checked <weekday> <d> <Mon> <yyyy>, <HH:MM>"; state 4 shows when any `problem_since` is more than 1 hour ago. Visibility: the card renders nothing when there is no planned outage and no problem older than 1 hour. Task 11 checks in the owner's HA that an empty markdown card is hidden. If it is not hidden, Task 11 adds a `visibility` condition, and you report the result to the owner.

- [ ] **Step 1: Write the failing test** — `test_blueprint.py` loads the YAML with HA's blueprint schema (`homeassistant.components.blueprint.models.Blueprint`) and asserts the four event triggers and the five inputs.
- [ ] **Step 2: Run** — `.venv/bin/pytest tests/test_blueprint.py -q` — Expected: FAIL.
- [ ] **Step 3: Write the blueprint and the card.**
- [ ] **Step 4: Run** — `.venv/bin/pytest -q && .venv/bin/ruff check .` — Expected: PASS.
- [ ] **Step 5: Update the documentation and the CI**
  - `README.md`: installation as a HACS custom repository; setup in the UI; how to find the station name (contract or customer portal); the entity table; the event table with payload keys; the blueprint import link (`https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=` + the raw GitHub URL); the card YAML; the YAML migration note: "New entity IDs. History of the old sensors does not carry over."
  - `hacs.json`: `{"name": "Elektro Celje Obvestila o izklopih", "homeassistant": "<min version from requirements_test.txt>", "render_readme": true}`.
  - `validate.yml`: `home-assistant/actions/hassfest@master` and `hacs/action@main` with `category: integration` and `ignore: brands` (brands come in stage 2).
  - `tests.yml`: `uv` + Python 3.13, `ruff check`, `pytest`.
- [ ] **Step 6: Push the branch and check the CI** — `git push -u origin redesign-v2`, then `gh run watch`. Expected: all jobs green. Ask the owner before you push.
- [ ] **Step 7: Commit, merge and release** — after the owner approves: merge to `master`, tag `v2.0.0`, `gh release create v2.0.0` with notes that contain the migration note.

---

### Task 11: Stage 1 in the owner's HA (needs the owner)

Work through the `ha-mcp` tools. Record the changes in the workspace repository `home-assitant` (backlog and audit), not in this repository. Confirm each HA change with the owner first.

- [ ] **Step 1:** Update the integration through HACS to `v2.0.0` and restart HA (with the owner's approval).
- [ ] **Step 2:** Check that the YAML import created `TP Zabukovica` (velenje, `zabukovica papež`) and `TP Lopata` (celje, `lopata oberžan`), and that the `deprecated_yaml` issue exists. Remove the YAML. Old entities `binary_sensor.tp_zabukovica` and `binary_sensor.tp_lopata`: search their consumers with `ha_search` first, then ask the owner before you remove them.
- [ ] **Step 3:** Add the card to a test dashboard. Check states 1, 2 and 4 with the live feed. Check that an empty card is hidden.
- [ ] **Step 4:** Import the blueprint and create an automation for the owner's phone. Fire a test event with `ha_call_event` and check that the notification arrives.
- [ ] **Step 5:** Ask the owner whether to remove the disabled automation `automation.send_notification_of_elektro_celje_rss_feed_title_when_updated`.
- [ ] **Step 6:** Tick the two `elektro_celje` items in `docs/backlog.md` of the workspace, and commit there.

### Stage 2 (not part of this plan)

Submission to the default HACS store starts only after the owner approves stage 1. It needs brand icons, `ignore: brands` removed from the CI, repository topics and description, and the HACS default-repository pull request. Write a separate plan for it then.
