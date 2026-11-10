# Elektro Celje Obvestila o izklopih

A Home Assistant integration for the planned power outages of Elektro Celje.
It reads the public RSS feeds of Elektro Celje. It finds the outages that
concern your transformer station (TP). It sends a notification to your
phones when an outage is new, when it changes, when it is no longer listed,
and on the day before.

This is an unofficial integration. It is not made or supported by Elektro
Celje. It reads their public RSS feeds.

The integration needs no account. It polls the feeds every 15 minutes.

## Installation

Install the integration from the Home Assistant Marketplace (formerly
HACS) as a custom repository. Home Assistant 2026.11 and newer has the
Marketplace built in.

1. Open **Settings > Marketplace**.
2. Select **Add from link**.
3. Enter `https://github.com/urosgruber/ha-elektro-celje`. The Marketplace
   asks you to connect GitHub the first time.
4. Download **Elektro Celje Obvestila o izklopih**.
5. Restart Home Assistant.

On Home Assistant older than 2026.11, use HACS instead. Open HACS, open the
menu, select **Custom repositories**, and add the same URL with the type
**Integration**.

## Setup

Set up each location in the UI.

1. Open **Settings > Devices & services > Add integration**.
2. Select **Elektro Celje Obvestila o izklopih**.
3. Enter a name, the region and the station query for the location.
   **Notify phones** lists the phones of the Home Assistant Companion app.
   All phones are selected. Keep them, or clear the list for no
   notifications.
4. Check the planned outages for the station, and select **Submit**.

Add the integration once for each location. A location is one station.

### How to find the station name

Enter the exact station name as the notices write it, without `TP`. The
match ignores case, accents and spacing only. A part of the name does not
match.

For example, enter `Zabukovica Papež`. The entry `Zabukovica` does not match
the notices for `Zabukovica Papež`.

The station is the transformer station (TP) that supplies your home. You find
its name on your electricity contract or in the Elektro Celje customer portal.
The setup form lists the station names that are in the feeds now. A station is
in the feeds only while it has a planned outage. If your station is not in the
list, type its name.

The reminder time is an option of each location. The default is 18:00.
The reminder ignores the quiet hours. It arrives at the reminder time that
you choose.

## Notifications

The integration sends the notifications itself. You need no automation and
no blueprint. Each location sends to its own phones.

- **Phones**: a phone is a `notify.mobile_app_*` action of the Companion app.
  A new location selects all phones. A location without phones sends no
  notification. A location that you added before 2.3.0 has no phones. To turn
  its notifications on, open the options of the location and select the
  phones.
- **Alerts**: a new outage, a reminder on the day before, a changed outage and
  a removed outage. The texts are in Slovenian when the language of Home
  Assistant is Slovenian. Otherwise they are in English. The texts are the
  built-in texts of the blueprint.
- **Tag**: a later notification of the same outage replaces the earlier one on
  the phone. Two outages of one notice give two notifications.

To change the phones, open **Settings > Devices & services > Elektro Celje
Obvestila o izklopih**, select the location, and select **Configure**.

### Quiet hours

Quiet hours are on by default, from 22:00 to 07:00. During the quiet hours,
a notification waits. It arrives when the quiet hours end.

- The reminder never waits. You chose its time, so it arrives at that time,
  also during the quiet hours. It does not replace a waiting notification.

- A notification about an outage that starts before the quiet hours end
  arrives at once.
- A notification about an outage with an unknown start waits.
- When a later alert of the same outage arrives during the quiet hours, it
  replaces the waiting one. A new outage that is removed again during the
  quiet hours sends nothing. A new outage that changes during the quiet hours
  sends one "new outage" notification with the new time.
- When the quiet hours end, a notification about an outage that has already
  ended is dropped.
- The waiting notifications survive a restart of Home Assistant.
- If the start and the end are the same time, no time is quiet.

The events of the integration never wait. Your own automations get them at
once.

### Switches

Each location has four switches in the **Configuration** group of its device:
**Notify: new outage**, **Notify: reminder**, **Notify: changed outage** and
**Notify: removed outage**. All are on by default. A switch that is off stops that kind of notification for
the location. The events still fire.

### Advanced: a quiet hours entity

The options have a collapsed section **Advanced**. There you can choose a
quiet hours entity: a Schedule helper, a Toggle helper (`input_boolean`) or a
binary sensor. The entity replaces the times. The notifications wait while
its state is `on`. They arrive when its state changes from `on` to a real
state, such as `off`. While the entity is missing, `unknown` or
`unavailable`, for example during a restart, the notifications keep waiting.
If the entity is still in that state 10 minutes after Home Assistant starts,
the integration treats it as not quiet and sends the notifications.

A Schedule helper is the easiest choice. It can have other quiet hours on
each day of the week. It also tells the integration when the quiet hours end,
so an outage that starts before then arrives at once. A Toggle helper or a
binary sensor does not tell the end. With such an entity, the notifications
wait until its state changes from `on`, even if the outage has already
started. Use a Schedule helper to avoid this.

The **Quiet hours** option must be on, also for the entity.

## Entities

Each location is one device. In the table, `<location>` is the name of the
device.

| Entity | Meaning |
|---|---|
| `sensor.<location>_planned_outages` | Number of planned outages. The `outages` attribute lists them. The `ended_today` attribute lists the outages that ended earlier today. |
| `sensor.<location>_next_outage_start` | Start of the next outage. |
| `sensor.<location>_next_outage_end` | End of the next outage. |
| `sensor.<location>_days_until_outage` | Days until the next outage. |
| `sensor.<location>_last_checked` | Time of the last attempt to read the feeds. During a long feed failure, it shows the time of the last state change of the location, not of the last attempt. Diagnostic. |
| `sensor.<location>_last_successful_check` | Time of the last successful read. Diagnostic. |
| `binary_sensor.<location>_outage_planned` | On when at least one outage is planned. |
| `binary_sensor.<location>_outage_now` | On while the power is off. |
| `binary_sensor.<location>_feed_problem` | On when a feed cannot be read. The `problem_since` attribute holds the start of the problem. Diagnostic. |
| `switch.<location>_notify_new_outage`, `_notify_reminder`, `_notify_changed_outage`, `_notify_removed_outage` | Turn one kind of notification on or off. Configuration. |
| `calendar.<location>_planned_outages` | The outages as calendar events. An outage that has ended stays in the calendar while the notice is in the feed. |

Entity IDs follow the names in your language. Check them in
**Settings > Devices & services**.

The `outages` attribute is a list. Each item has `start`, `end`, `all_day`,
`status`, `station`, `region`, `text` and `link`. The `status` is `ok`,
`date_only` or `failed`. When `status` is `failed`, the integration could not
read the time. `start` and `end` are then empty.

The `ended_today` attribute has the same item format. It lists the outages
that ended earlier today, in the `Europe/Ljubljana` time zone. It lists only
outages with the status `ok` or `date_only`. The notice must still be in the
feed. The list is empty after local midnight. The attribute is not recorded
in the history.

## Advanced: blueprint and events

Use the events and the blueprint when you want more than the built-in
notifications: your own texts, other actions, or notifications for some
locations only. If you use the blueprint, clear the phones of the location in
its options. Otherwise each phone gets two notifications.

### Events

The integration fires these events. The phones, the quiet hours and the
switches do not change them. Each event fires once for each outage.

| Event | When |
|---|---|
| `elektro_celje_outage_detected` | The integration finds a new outage. |
| `elektro_celje_outage_reminder` | At the reminder time, on the day before an outage. |
| `elektro_celje_outage_changed` | The time of a known outage changes. |
| `elektro_celje_outage_removed` | A notice is no longer in a feed that the integration read successfully. The outage has not ended yet. |

If the integration finds an outage after the reminder time on the day before,
it fires only `detected`.

Payload of every event:

| Key | Meaning |
|---|---|
| `location` | Name of the location. |
| `entry_id` | ID of the config entry. |
| `notice_id` | ID of the notice in the feed. |
| `key` | ID of the outage, `<notice_id>:<index>`. A notice with two dates gives two outages with two keys. |
| `region` | Region of the notice. |
| `station` | Station text of the notice. |
| `start`, `end` | ISO times, or `null` when unknown. |
| `all_day` | `true` for an outage that lasts all day. |
| `duration_minutes` | Duration, or `null` when unknown. |
| `status` | `ok`, `date_only` or `failed`. |
| `text` | Text of the notice. |
| `link` | Link to the notice. |
| `old_start`, `old_end` | Only for `changed`. The earlier times. |

The wording for `removed` is "no longer listed". The feed does not say why a
notice disappears.

### Notification blueprint

The blueprint sends a mobile app notification for the four events. You select
the phone and the events. The notification tag is the config entry ID and the
outage `key`. A change replaces the earlier notification of the same outage.
Two outages of one notice give two notifications. A change shows the earlier
time and the new time.

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Furosgruber%2Fha-elektro-celje%2Fmaster%2Fblueprints%2Fautomation%2Felektro_celje%2Foutage_notify.yaml)

The link opens this URL in your Home Assistant:
`https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/urosgruber/ha-elektro-celje/master/blueprints/automation/elektro_celje/outage_notify.yaml`

The blueprint groups its inputs in four sections:

- **Phone**: the device that receives the notification.
- **Alerts**: four switches, one for each event. All are on by default.
- **Locations**: **Locations (pick)** lets you pick any entity of each
  location. **Locations (names)** takes location names, separated by commas.
  If both are empty, you get alerts for all locations. If you fill both, an
  outage of any listed location sends a notification.
- **Texts** (collapsed): the language, one title for each event and the
  message.

The blueprint needs Home Assistant 2024.10.0 or newer. The old inputs keep
their names and meaning. An automation that you made with an earlier version
works unchanged and gives the same Slovenian texts.

#### Texts

**Language** is `Slovenščina` (default) or `English`. English example:
"Planned power outage" and "TP lopata: 12 Nov 2026, 08:00–14:00 (6 h)".

Leave a title or the message empty to use the built-in text. To write your
own, use these placeholders in the titles and in the message:

| Placeholder | Value |
|---|---|
| `{location}` | The location name. |
| `{when}` | The date and time, "all day", or "time unknown". |
| `{old_when}` | The earlier time. Empty unless the outage changed. |
| `{duration}` | The length, for example "2 h 30 min". Empty if unknown. |
| `{station}` | The transformer station. |
| `{text}` | The text of the notice. |
| `{link}` | The link to the notice. |

Example message: `{location}: {when} ({duration}), {station}`. This gives
"Dom: 12 Nov 2026, 08:00–14:00 (6 h), TP lopata".

The blueprint joins all white space into single spaces. The notice text comes
from the feed, so the blueprint never runs it as a template. It puts each
value in as plain text. A value that contains `{location}` stays as it is.

## Dashboard card

The integration ships its own card. Add the card to a dashboard:

```yaml
type: custom:elektro-celje-card
```

You can also find the card in the card picker. Its name is
**Elektro Celje outages**. The integration registers the card itself. You do
not add a dashboard resource. After you install or update the integration,
restart Home Assistant. Then hard-reload the browser, so it loads the new card.

The card has one option. `title` adds a heading to the card.

The card shows all outages of all locations.
The integration builds all texts of the card. The card only draws them. The texts are in Slovenian when the
language of Home Assistant is Slovenian. Otherwise they are in English.

- A banner shows the outage that happens now, or else the next outage.
- Each other outage that happens now has its own red banner.
- A red banner counts down to the end of the outage, for example
  "ends in 1 h 12 min". The card updates this text once a minute.
- **Also planned** lists the other outages, grouped by day. The banner outage
  is not in this list.
- **Ended today** lists the outages that ended earlier today. The text is
  small and grey. The section has no banner.
- A grey banner shows a feed problem that is older than one hour.
- The footer shows the oldest good check of all locations.

The card hides itself when no outage is planned, no outage ended today, and
no feed problem is older than one hour. In the dashboard editor, the card
shows the text "Elektro Celje: nothing planned", so you can find it.
The card uses the colours of your theme. It works with light and dark themes.

To see the card without Home Assistant, open `docs/card-preview.html` in a
browser. The page shows the card with example data.

### Markdown card (fallback)

If you cannot use the custom card, use a standard Markdown card. The file
`docs/dashboard-card.yaml` has the same card as a Markdown card. The Markdown
card is empty when the custom card is hidden. If your dashboard still shows
an empty card frame, wrap the card in a **Conditional** card, or add a
visibility condition on the card.

The `planned_outages` sensor has these attributes for the card. They are not
recorded in the history. Do not use them in automations. Use `outages` and
`ended_today` instead.

| Attribute | Meaning |
|---|---|
| `card` | A list of ready items. Each has `location`, `group`, `sort`, `title`, `detail`, `day`, `row`, `span` and `chip`. `span` is the time and the length. `chip` is the relative day, for example "in 3 days". The `group` is `live`, `next` or `ended`. A `live` item also has `end`, the end in UTC, so the card can count down. |
| `card_labels` | The headings `also_planned` and `ended_today`, the text `now`, and the countdown templates `ends_in`, `hours_minutes`, `hours` and `minutes`. |
| `card_footer` | The text "Checked ..." with the last good check. |
| `card_problem` | A text when a feed problem lasts more than one hour. Otherwise `null`. |
| `card_problem_title`, `card_problem_detail` | The same problem in two parts: a title and a short second line. Otherwise `null`. |

All times and dates use `Europe/Ljubljana`. The texts change at each update
and at local midnight, so "tomorrow" stays right. The card shows the device
name. If you rename the device, the new name shows at the next update.

```yaml
type: markdown
content: |
  {#- The integration builds all texts. This card only loops and prints. -#}
  {%- set ns = namespace(items=[], problem='', foot='', stamp='', labels={}) -%}
  {%- for e in integration_entities('elektro_celje') if state_attr(e, 'card') is not none -%}
    {%- set ns.items = ns.items + state_attr(e, 'card') -%}
    {%- set ns.labels = state_attr(e, 'card_labels') -%}
    {%- set ns.problem = ns.problem or state_attr(e, 'card_problem') or '' -%}
    {%- set ts = state_attr(e, 'last_success') or '' -%}
    {%- if state_attr(e, 'card_footer') and (not ns.stamp or ts < ns.stamp) -%}
      {%- set ns.stamp = ts -%}{%- set ns.foot = state_attr(e, 'card_footer') -%}
    {%- endif -%}
  {%- endfor -%}
  {%- set live = ns.items | selectattr('group', 'eq', 'live') | sort(attribute='sort') | list -%}
  {%- set nxt = ns.items | selectattr('group', 'eq', 'next') | sort(attribute='sort') | list -%}
  {%- set ended = ns.items | selectattr('group', 'eq', 'ended') | sort(attribute='sort') | list -%}
  {%- set banner = (live + nxt) | first | default(none) -%}
  {%- set rest = nxt[(0 if live else 1):] -%}
  {%- if ns.items or ns.problem -%}
  {%- if ns.problem %}

  <ha-alert alert-type="info">⚠ {{ ns.problem }}</ha-alert>
  {% endif -%}
  {%- if banner %}

  <ha-alert alert-type="{{ 'error' if live else 'warning' }}" title="{{ '🔌' if live else '⚡' }} {{ banner.title }}">
  {{ banner.location }}{{ ' · ' ~ banner.detail if banner.detail }}
  </ha-alert>
  {% endif -%}
  {%- for b in live[1:] %}

  <ha-alert alert-type="error" title="🔌 {{ b.title }}">
  {{ b.location }}{{ ' · ' ~ b.detail if b.detail }}
  </ha-alert>
  {% endfor -%}
  {%- if rest %}

  **{{ ns.labels.also_planned }}**
  {% for i in rest -%}
  {%- if loop.first or i.day != loop.previtem.day %}

  **{{ i.day }}**
  {% endif %}
  - **{{ i.location }}** · {{ i.row }}
  {%- endfor %}
  {% endif -%}
  {%- if ended %}

  <small>{{ ns.labels.ended_today }}</small><br>
  {% for i in ended -%}
  <small>*✓ {{ i.location }} · {{ i.title }}*</small>{{ '<br>' if not loop.last }}
  {% endfor -%}
  {%- endif %}

  {% if ns.foot -%}*{{ ns.foot }}*{%- endif %}
  {%- endif %}
```

## Icon

The integration ships its own icon. The files are
`custom_components/elektro_celje/brand/icon.png` and `icon@2x.png`. It is an original drawing. It is not the logo of Elektro
Celje. The script `scripts/make_icon.py` draws it. Run
`.venv/bin/python scripts/make_icon.py` to draw it again.

## Migration from the YAML version

The old YAML platform `binary_sensor: - platform: elektro_celje` is
deprecated. On start, the integration imports each YAML entry as a config
entry. It then creates a repair issue. Remove the YAML entry when you see it.

**New entity IDs. History of the old sensors does not carry over.**

Update your automations and dashboards to the new entities.

## Troubleshooting

If a problem lasts, open the diagnostics of the integration. Then open an
issue on GitHub. The `binary_sensor.<location>_feed_problem` entity shows
when a feed cannot be read.

The diagnostics file shows the public region feeds and only the status of
your outages. It redacts the location name and the station query. It does not
show the times or the notices of your outages. Check the file
before you attach it to an issue.

Do not paste raw entity states or the `outages` attribute into a public
issue. They contain your station name.

## Contributing

Pull requests are welcome. Run `ruff check .`, `ruff format --check .` and
`pytest -q` before you open one.

## Changelog

- 2.3.0: built-in phone notifications for each location, with quiet hours,
  four switches and an optional quiet hours entity. The blueprint stays as an
  advanced option.

## License

MIT License.
