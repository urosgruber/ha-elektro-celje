# Elektro Celje planned outages: redesign

Date: 2026-11-09
Status: approved by the owner on 2026-11-09
Repository: `urosgruber/ha-elektro-celje` (domain `elektro_celje`, now version 1.0.8)

## 1. Intent

Elektro Celje publishes planned power outages in four RSS feeds. The
integration matches a station name in a feed and shows the result in Home
Assistant (HA).

Today the owner learns about an outage only when the power is already off.
The goal is to know early, and to know the exact day and hours, for every
location the owner watches.

The second goal is quality. The owner wants to publish the integration in
the default HACS store, so that other Elektro Celje customers can use it.

## 2. Current state

The current code is in `custom_components/elektro_celje/`. It has these
defects. The redesign must remove all of them.

| Defect | Effect |
|---|---|
| The parser reads only `08:00` times. The feed also uses `8:00`, `08.30` and `09.november`. | The parser fails on 30 of 51 items in the 2026-11-09 feeds. |
| A fetch error returns the same result as "no match". | A network error turns the sensor off. This is a false all-clear. |
| The parser keeps only the first matching notice. | A second outage at the same station is lost. One example is Spodnji Žusem on 10 and 12 November. |
| The binary sensor is on while the station is in the feed. | It does not tell "planned" from "now" from "over". On 2026-11-09 it was on at 16:23 for an outage that ended at 11:00. |
| `async_update` reads `self.hass.states.get(self.entity_id)` before HA adds the entity. | The sensor logs an error on every start. |
| Datetimes have no time zone. | Consumers cannot interpret them safely. |
| The `unique_id` comes from the editable name. | A rename changes the identity. Two locations with the same name collide. |
| The configuration is YAML only. The manifest has invalid keys and a placeholder URL. There are no tests and no CI. | The integration cannot go into the default HACS store. |

A full independent review by Codex is in the session notes. Section 12 lists
its findings that this document uses.

## 3. Goals

1. The user adds, edits and removes each location in the HA UI.
2. The integration shows every planned outage for every location, with the
   date, the start time, the end time and the number of days until it starts.
3. The integration alerts the user at four moments:
   - when it detects a new outage,
   - on the day before an outage,
   - when the time of an outage changes,
   - when a notice is removed from the feed.
4. A dashboard card shows planned outages as soon as the integration detects
   them, at any distance in the future.
5. The entities show debug data: when the feed was checked (with the full
   date), the source URL, the notice text and the parse result.
6. The integration is good enough for the default HACS store.

## 4. Non-goals

- Unplanned outages (faults, storms). The feeds contain only planned work.
- Other distributors, such as Elektro Ljubljana or Elektro Maribor.
- A timeline card, with one line per location. The owner rejected it.
- Sending notifications directly from the integration. A blueprint does this.

## 5. Anti-goals

These results are failures, even if every feature works.

- **A false all-clear.** The integration must never show "no outage" when
  it could not read the feed, or when it could not parse a notice.
- **A silent miss.** If a notice matches the station but the parser cannot
  read the time, the notice must still appear on the card and in an alert,
  with its full text.
- **Repeated alerts.** One event gives one alert. A restart or a repeated
  poll must not send it again.
- **A "removed" alert for an outage that is over.** Notices leave the feed
  after the outage. That is not news.

## 6. Decisions by the owner

These decisions come from the owner. Do not change them without asking.

- **Locations in the UI.** Each location has a name, a region and a station
  query.
- **The card is visible only when an outage is planned.** It appears as soon
  as the integration detects an outage. There is no 48-hour limit. When
  nothing is planned, the card is hidden.
- **The card layout is version 4 of the mockups** (a combination of options
  A and C):
  - A banner at the top shows one outage: the current outage, or else the
    next one.
  - Below the banner, "Also planned" lists the other outages, grouped by
    day. The banner outage is not repeated in the list.
  - Each row shows the location, the time range, the duration and a
    countdown ("in 3 days").
  - During an outage the banner is red and shows when it ends.
  - The footer shows the check time with the full date, for example
    "Checked Mon 9 Nov 2026, 16:23 · elektro-celje.si".
- **All outages are shown.** Two outages at one location are two rows.
  Outages at two locations are separate rows.
- **Alerts:** on detection, on the day before, on a time change and on
  removal (see goal 3).
- **Release in two stages.**
  1. Install from the GitHub repository as a custom repository in the
     owner's HA (the local marketplace). The owner tests it there.
  2. Submit to the default HACS store when the owner is happy.

The mockup is in `docs/superpowers/specs/2026-11-09-dashboard-mockup-v4.html`.
It is an HTML fragment. It shows the four card states with example data.

## 7. Design

Sections 7.1 to 7.8 describe the design. Items marked **(my call)** are
choices that the designer made and the owner has not confirmed. The owner
can change them.

### 7.1 Feed facts

- There are four feeds: `https://www.elektro-celje.si/si/rss.ashx?k=<slug>`,
  with the slugs `celje`, `velenje`, `krsko` and `slovenj-gradec`. All four
  answered on 2026-11-09.
- Each `<item>` has a `title`, a `link`, a `pubDate` and an HTML
  `description`. There is no `guid`.
- The station text is in the first `<strong>` of the description. The date
  and time are in `<ul class="dates-list"><li>…</li></ul>`.
- `pubDate` is not reliable. Sometimes it is the publish time. Sometimes it
  is the outage date at 00:00.
- On 2026-11-09 every item had exactly one `<li>`. Multi-day notices may
  have more than one `<li>`. The parser must accept more than one.
- The date and time formats seen on 2026-11-09:

  | Example | Count |
  |---|---|
  | `09. novembra 2026, … med 08:30 in 11:30 uro` | 20 |
  | `10. novembra 2026, … med 8:00 in 13:00 uro` | 17 |
  | `9. novembra 2026, … med 8:00 in 14:00 uro` | 8 |
  | `09. novembra 2026, … med 08.30 in 11.00 uro` | 3 |
  | `09.november 2026, … med 08:00 in 11:00 uro` | 1 |
  | `9. november 2026, … med 9:00 in 13:30 uro` | 1 |
  | `11. november 2026, … med 8:00 in 8:30 uro` | 1 |

- The month can be in the genitive (`novembra`) or the nominative
  (`november`). The parser must map all Slovenian month forms to month
  numbers. It must not depend on the system locale.

### 7.2 Configuration

- **One config entry per location.**
- The setup form has three fields:
  - **Name**, for example "Home" or "TP Zabukovica". It is required.
  - **Region**: Celje, Velenje, Krško, Slovenj Gradec, or "All regions".
    The default is "All regions" **(my call)**. Users often do not know
    their region. With "All regions" the location uses all four feeds.
  - **Station**, for example "Zabukovica Papež". It is required and must
    not be empty. Users find this name in their contract or in the
    Elektro Celje customer portal.
- **The form shows a preview.** After the user enters the station, the form
  shows the notices that match now, with the full text and the region. An
  empty preview is normal. The form must say that no outage is planned now,
  and that this is not an error.
- **The user can edit a location** (reconfigure) without deleting it.
- **Options** (my calls):
  - Reminder time for the day-before alert. The default is 18:00.
- The `unique_id` of the entry comes from the normalized station query and
  the region. Two entries with the same station and region are rejected.

### 7.3 Matching

**A location matches exactly one station.** This is the owner's decision.
"Žusem" matches the station "Žusem". It does not match "Spodnji Žusem" or
"Zgornji Žusem".

- **The station text** is the plain text of the first `<strong>` in the
  description, after HTML removal and whitespace normalization. The rest of
  the description is not searched. Matching on raw HTML is not allowed.
- **The integration splits the station text into station names:**
  1. Cut the text at the first feeder marker. The markers are ` - `, ` – `
     (en dash), and a part that starts with `nizkonapetostn` or `izvod`.
     The text after the marker names the feeder, not the station.
  2. Split the rest at `,` and at the word ` in `.
  3. Trim each name.
- **The query matches when it equals one station name**, after both are
  normalized. Normalization ignores case, accents and repeated spaces.
  "zabukovica papez" equals "Zabukovica Papež". There is no partial match.
- **A feeder outage counts for the whole station** (my call). The notice
  "Zabukovica Papež - nizkonapetostni izvod Kozovinc" matches the location
  "Zabukovica Papež", even if the user is on another feeder. A false alarm
  is better than a miss (section 5). A feeder filter can come later.
- **If a notice has no `<strong>`,** it matches no location. The notice gets
  the parse warning "no station text" in diagnostics, and the
  `feed_problem` entity shows a warning.
- **The setup form suggests station names** (my call). It lists the station
  names that are in the selected feeds now. The user can select one or type
  a name. Typed names are needed, because the feed lists a station only
  while it has a planned outage.
- **Expected results**, from the 2026-11-09 fixtures:

  | Station text | Station names |
  |---|---|
  | Zabukovica Papež - nizkonapetostni izvod Kozovinc | `Zabukovica Papež` |
  | Babna Reka in Baberšica | `Babna Reka`, `Baberšica` |
  | Žegar, nizkonapetostno omrežje - Vodovod | `Žegar` |
  | Mokronog nadzorništvo, nizkonapetostno omrežje – Puščava vas | `Mokronog nadzorništvo` |
  | Podgorje Vravar - izvod Podgorje 103, 104 in 104a | `Podgorje Vravar` |
  | Impolje, Orle, Prlska gora, Zavratec ribnik, Dedna gora in Studenec Matko | `Impolje`, `Orle`, `Prlska gora`, `Zavratec ribnik`, `Dedna gora`, `Studenec Matko` |
  | Stanovanjske hiše Kotlje od št.88 do št.97 | `Stanovanjske hiše Kotlje od št.88 do št.97` |

  | Query | Station text | Match |
  |---|---|---|
  | `zabukovica papež` | Zabukovica Papež - nizkonapetostni izvod Kozovinc | yes |
  | `zabukovica` | Zabukovica Papež - nizkonapetostni izvod Kozovinc | no |
  | `žusem` | Spodnji Žusem | no |
  | `žusem` | Glažuta, …, Loka pri Žusmu, Žusem, Dobrina, … | yes |
  | `studenec` | Studenec | yes |
  | `studenec` | …, Dedna gora in Studenec Matko | no |

- **The test suite checks the split for all 51 fixture notices.**
- **The owner's queries must keep working.** They are `zabukovica papež`
  (region `velenje`) and `lopata oberžan` (region `celje`). The YAML import
  copies them unchanged. The owner confirmed that "Lopata Oberžan" is the
  exact station name. It is not in the 2026-11-09 feeds.

### 7.4 Data model

- **Notice**: one feed `<item>`.
  - The notice ID is the numeric ID in the `link` URL, for example `43309`
    in `…/2026/11/43309-993-Nadzornistvo-…`. Do not use the whole URL: it
    contains a slug from the title and `:443`. The title number ("993.") is
    not unique. If a link has no numeric ID, use a hash of the region, the
    station text and the date text.
  - Fields: ID, region, title, link, plain text, matched station text,
    intervals, parse status, first seen time, last seen time.
- **Interval**: one `<li>`. Fields: start and end, as aware datetimes in
  `Europe/Ljubljana`.
- **Parse status**: `ok`, `date_only` or `failed`, with a reason. A notice
  that is not `ok` keeps its text and still counts as a planned outage. See
  the anti-goals in section 5.
- **Rules for a notice that is not `ok`** (my call):

  | Status | Date | Time | Calendar | Counts as planned until | Reminder | `removed` alert |
  |---|---|---|---|---|---|---|
  | `date_only` | known | unknown | all-day event | the end of that day | yes, the day before | only if removed before the end of that day |
  | `failed` | unknown | unknown | no event | it leaves the feed | no | no |

  - A `failed` notice shows on the card with the text "time unknown" and the
    notice text. Its `detected` alert says that the time is unknown and
    contains the full notice text.
  - A `failed` notice does not get a `removed` alert, because the
    integration cannot tell whether the outage is over.

- **Changed time** (my call): a notice that keeps its numeric ID and gets
  new intervals fires `changed`. The integration does not pair a removed
  notice with a new notice. If Elektro Celje publishes a new notice for a
  new time, the user gets `removed` and `detected`. The owner does not lose
  information in this case. Collect real examples, and add pairing later if
  this happens often.
- **Outage**: one interval of one notice at one location. The card, the
  calendar and the alerts work with outages.

### 7.5 Data updates

- **One coordinator per region feed**, shared by all locations that use the
  feed. A location with "All regions" uses all four coordinators.
- **The poll interval is 15 minutes** (my call). Notices sometimes appear
  only one hour before the outage. For example, the Zabukovica notice
  appeared at 07:32 for an outage at 08:30.
- Use the HA shared HTTP session, a timeout and a User-Agent that names the
  integration. Do not use `feedparser.parse(url)` to download.
- **A failed fetch is a failure, not an empty result.** With "All regions",
  one failed feed out of four is a failure for that location.
  - The entities keep the last good data.
  - A diagnostic entity shows the problem.
  - The card shows state 4 ("Cannot read the Elektro Celje feed").
  - No "removed" alerts are sent while the feed fails.
- **Time changes without polling.** "Outage now" and the day countdown must
  change at the start time, at the end time and at midnight. They must not
  wait for the next poll.
- **The integration stores data across restarts.** It stores the known
  notices, the first seen times and the alerts it has sent, in the HA
  storage helper.

### 7.6 Entities per location

All entities belong to one device per location.

| Entity | Meaning |
|---|---|
| `calendar.<loc>_planned_outages` | One event per outage. The event description holds the notice text and the link. |
| `binary_sensor.<loc>_outage_planned` | On when at least one outage has not ended yet. This includes outages with an unknown time. |
| `binary_sensor.<loc>_outage_now` | On when an outage is in progress now, by the published times. |
| `sensor.<loc>_next_outage_start` | A timestamp. It is unknown when no outage is planned. |
| `sensor.<loc>_next_outage_end` | A timestamp. |
| `sensor.<loc>_days_until_outage` | Calendar days in `Europe/Ljubljana`. It is 0 on the day of the outage. It is unknown, not 0, when no outage is planned. |
| `sensor.<loc>_planned_outages` | The number of outages that have not ended. An attribute `outages` lists all of them, for the dashboard card. |
| `sensor.<loc>_last_checked` (diagnostic) | The time of the last fetch attempt. |
| `sensor.<loc>_last_successful_check` (diagnostic) | The time of the last good fetch. |
| `binary_sensor.<loc>_feed_problem` (diagnostic) | On when the last fetch or parse failed. |

- **Debug attributes** on `planned_outages` and `outage_planned`: source
  feed URL(s), notice link, notice text (plain, limited in length), matched
  station text and parse status.
- Large attributes must not go into the recorder. Use
  `_unrecorded_attributes`.
- **HA diagnostics** (the "Download diagnostics" button) returns the raw
  feed items, the parse results and the alert state. It must redact the
  location name and the station query.

### 7.7 Alerts

- **The integration fires HA events.** It does not send notifications.

  | Event | When |
  |---|---|
  | `elektro_celje_outage_detected` | A new outage is found for a location. |
  | `elektro_celje_outage_reminder` | At the reminder time (default 18:00) on the day before the outage. |
  | `elektro_celje_outage_changed` | The time of a known outage changes. |
  | `elektro_celje_outage_removed` | A notice is no longer in a feed that was read successfully, and the outage has not ended yet. |

- **Event data:** location name, config entry ID, notice ID, start, end,
  duration, notice text, link, region, and for `changed` the old start and
  end.
- **The wording for removal is "no longer listed".** It is not "cancelled",
  because the feed does not give a reason.
- **One event fires once.** The integration stores which events it has
  fired. A restart or a repeated poll must not fire them again. A changed
  outage gets a new reminder at the new time.
- **Late detection.** If the integration first detects an outage after the
  reminder time on the day before, it fires only `detected`, not also
  `reminder` **(my call)**.
- **A blueprint comes with the integration.** It turns the events into
  notifications. The user selects the notify target and which of the four
  events to send. It uses the notification tag, so a change replaces the
  earlier notification.

### 7.8 Dashboard card

- The README gives a copy-and-paste card. It must look like mockup
  version 4.
- **The card is visible in two cases** (my call):
  - At least one location has an outage that has not ended.
  - At least one location has had `feed_problem` on for more than 1 hour.
    This shows state 4 also when no outage is known, for example on a first
    install. A hidden card in that case would look like an all-clear. The
    1-hour delay stops the card from flashing on a short network error.
- First try **standard HA cards only** (my call): a conditional card plus a
  markdown card that reads the `outages` attributes of all locations, for
  example with `integration_entities('elektro_celje')`.
- If standard cards cannot reach the mockup quality, the builder may ship a
  custom card. Ask the owner first, because it adds a frontend build.

## 8. Migration from YAML

- The YAML platform `binary_sensor: - platform: elektro_celje` is
  deprecated.
- On start, the integration imports each YAML entry into a config entry
  (import flow). It then creates a repair issue that tells the user to
  remove the YAML.
- The new entity IDs can differ from the old ones. History of the old
  entities is not carried over. The release notes must say this.

## 9. Release

### Stage 1: owner test (local marketplace)

- Release a new major version, for example 2.0.0, on GitHub.
- The owner installs it as a HACS custom repository and replaces the two
  YAML sensors (`TP Zabukovica`, region `velenje`; `TP Lopata`, region
  `celje`).
- Changes in the owner's own HA (the card, the blueprint automation, the
  removal of the disabled `feedreader` automation) are tracked in the
  workspace repository `home-assitant`, not here.

### Stage 2: default HACS store

Only after the owner approves stage 1.

- The CI passes: `hassfest`, HACS validation, pytest and Ruff.
- The repository has a description, topics, issues and releases.
- Brand icons exist, as HACS requires.
- The manifest is correct: real documentation URL, `issue_tracker`,
  `codeowners`, pinned requirements, and no invalid keys.
- English and Slovenian translations exist for the config flow, the
  entities, the repair issues and the blueprint.

## 10. Tests

- The four feeds from 2026-11-09 are in `tests/fixtures/`. They are the
  baseline.
- The parser must read **all 51 items** with the exact expected start and
  end. Write the expected values by hand from the fixture text.
- Test every row of the match table in section 7.3.
- Also test: more than one `<li>`; a `date_only` notice; a `failed` notice; a notice with an unreadable time; an
  empty feed; a failed fetch; a notice that changes time; a notice that is
  removed before and after its end; a restart with stored alert state; the
  countdown at midnight; and the DST change.
- Collect new fixtures when the feed shows a new format.

## 11. Left to the builder

- Module layout, class names and dependencies. Fewer dependencies are
  better.
- The HTML and XML parsing method.
- The minimum HA version. Choose the oldest version that the tests pass on.
- The exact entity names and translation keys.
- The event payload format, within section 7.7.
- Whether `outage_planned` and `outage_now` also carry the debug
  attributes, or only `planned_outages`.

## 12. Sources

- The owner's conversation on 2026-11-09.
- The live feeds from 2026-11-09, saved in `tests/fixtures/`.
- The HA state of `binary_sensor.tp_zabukovica` and `binary_sensor.tp_lopata`
  on 2026-11-09.
- An independent code review by Codex on 2026-11-09. This document uses its
  findings on the duplicate notice (Spodnji Žusem), the unreliable
  `pubDate`, the missing `guid`, whole-word matching, the shared regional
  coordinator, the scheduled time changes and the "no longer listed" wording.
