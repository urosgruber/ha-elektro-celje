# Elektro Celje Obvestila o izklopih

A Home Assistant integration for the planned power outages of Elektro Celje.
It reads the public RSS feeds of Elektro Celje. It finds the outages that
concern your transformer station (TP). It sends an alert when an outage is
new, when it changes, when it is no longer listed, and on the day before.

The integration needs no account. It polls the feeds every 15 minutes.

## Installation

Install the integration as a HACS custom repository.

1. Open HACS in Home Assistant.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/urosgruber/ha-elektro-celje` with the type
   **Integration**.
4. Download **Elektro Celje Obvestila o izklopih**.
5. Restart Home Assistant.

## Setup

Set up each location in the UI.

1. Open **Settings > Devices & services > Add integration**.
2. Select **Elektro Celje Obvestila o izklopih**.
3. Enter a name, the region and the station query for the location.

Add the integration once for each location. A location is one station.

### How to find the station name

The station name is the name of the transformer station (TP), for example
`TP Zabukovica`. You find it on your electricity contract or in the Elektro
Celje customer portal. Enter a part of the name. The match ignores case and
diacritics.

The reminder time is an option of each location. The default is 18:00.

## Entities

Each location is one device. In the table, `<location>` is the name of the
device.

| Entity | Meaning |
|---|---|
| `sensor.<location>_planned_outages` | Number of planned outages. The `outages` attribute lists them. |
| `sensor.<location>_next_outage_start` | Start of the next outage. |
| `sensor.<location>_next_outage_end` | End of the next outage. |
| `sensor.<location>_days_until_outage` | Days until the next outage. |
| `sensor.<location>_last_checked` | Time of the last attempt to read the feeds. Diagnostic. |
| `sensor.<location>_last_successful_check` | Time of the last successful read. Diagnostic. |
| `binary_sensor.<location>_outage_planned` | On when at least one outage is planned. |
| `binary_sensor.<location>_outage_now` | On while the power is off. |
| `binary_sensor.<location>_feed_problem` | On when a feed cannot be read. The `problem_since` attribute holds the start of the problem. Diagnostic. |
| `calendar.<location>_planned_outages` | The outages as calendar events. |

Entity IDs follow the names in your language. Check them in
**Settings > Devices & services**.

The `outages` attribute is a list. Each item has `start`, `end`, `all_day`,
`status`, `station`, `region`, `text` and `link`. The `status` is `ok`,
`date_only` or `failed`. When `status` is `failed`, the integration could not
read the time. `start` and `end` are then empty.

## Events

The integration fires these events. It does not send notifications by itself.
Each event fires once for each outage.

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

## Notification blueprint

The blueprint sends a mobile app notification for the four events. You select
the phone and the events. A change replaces the earlier notification.

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Furosgruber%2Fha-elektro-celje%2Fmaster%2Fblueprints%2Fautomation%2Felektro_celje%2Foutage_notify.yaml)

The link opens this URL in your Home Assistant:
`https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/urosgruber/ha-elektro-celje/master/blueprints/automation/elektro_celje/outage_notify.yaml`

The notification texts are in Slovenian.

## Dashboard card

The card is a standard Markdown card. It shows all outages of all locations.
The card is empty when no outage is planned and no feed problem is older than
one hour. If your dashboard still shows an empty card frame, wrap the card in
a **Conditional** card, or add a visibility condition on the card.

Texts are in a small dictionary at the top of the template. Change them to
translate the card.

```yaml
type: markdown
content: |
  {#- Texts. Change the values to translate the card. -#}
  {%- set L = {
    'next': 'Next outage',
    'now': 'Outage now',
    'ends_in': 'ends in',
    'also': 'Also planned',
    'checked': 'Checked',
    'last_good': 'Last good check',
    'feed_error': 'Cannot read the Elektro Celje feed',
    'list_old': 'the list below may be old',
    'problem_since': 'Problem since',
    'unknown_time': 'time unknown',
    'unknown_day': 'Date unknown',
    'all_day': 'all day',
    'today': 'Today',
    'tomorrow': 'Tomorrow',
    'in_today': 'today',
    'in_tomorrow': 'tomorrow',
    'in_day': 'in 1 day',
    'in_days': 'in {n} days',
    'h': 'h',
    'min': 'min',
  } -%}
  {%- macro dur(m) -%}
    {%- set h = m // 60 -%}{%- set r = m % 60 -%}
    {{- [(h ~ ' ' ~ L.h) if h else '', (r ~ ' ' ~ L.min) if r else ''] | select | join(' ') -}}
  {%- endmacro -%}
  {%- macro daydiff(s) -%}{{ (s.date() - now().date()).days }}{%- endmacro -%}
  {%- macro rel(d) -%}
    {%- if d <= 0 -%}{{ L.in_today }}
    {%- elif d == 1 -%}{{ L.in_tomorrow }}
    {%- else -%}{{ L.in_days.format(n=d) }}{%- endif -%}
  {%- endmacro -%}
  {%- macro span(i) -%}
    {%- if i.s is none -%}{{ L.unknown_time }}
    {%- elif i.all_day -%}{{ L.all_day }}
    {%- else -%}{{ i.s.strftime('%H:%M') }} – {{ i.e.strftime('%H:%M') if i.e else '?' }}
    {%- if i.e %} · {{ dur(((i.e - i.s).total_seconds() // 60) | int) }}{% endif -%}
    {%- endif -%}
  {%- endmacro -%}

  {#- Collect the outages and the problems of all locations. -#}
  {%- set now_ = now() -%}
  {%- set ns = namespace(items=[], problem=none, oldest=none) -%}
  {%- for ent in integration_entities('elektro_celje') -%}
    {%- set attrs = states[ent].attributes if states[ent] is not none else {} -%}
    {%- set dev = device_id(ent) -%}
    {%- set name = (device_attr(dev, 'name_by_user') or device_attr(dev, 'name') or ent) if dev else ent -%}
    {%- if ent.startswith('sensor.') and 'outages' in attrs -%}
      {%- for o in attrs.outages -%}
        {%- set s = as_local(as_datetime(o.start)) if o.start else none -%}
        {%- set e = as_local(as_datetime(o.end)) if o.end else none -%}
        {%- if e is none or e > now_ -%}
          {%- set ns.items = ns.items + [{
            'loc': name, 's': s, 'e': e, 'all_day': o.all_day, 'text': o.text,
            'key': as_timestamp(s) if s else 9e12}] -%}
        {%- endif -%}
      {%- endfor -%}
      {%- if attrs.last_success -%}
        {%- set ok = as_local(as_datetime(attrs.last_success)) -%}
        {%- set ns.oldest = ok if ns.oldest is none or ok < ns.oldest else ns.oldest -%}
      {%- endif -%}
    {%- elif ent.startswith('binary_sensor.') and attrs.get('problem_since') -%}
      {%- set p = as_local(as_datetime(attrs.problem_since)) -%}
      {%- if (now_ - p).total_seconds() > 3600 -%}
        {%- set ns.problem = p if ns.problem is none or p < ns.problem else ns.problem -%}
      {%- endif -%}
    {%- endif -%}
  {%- endfor -%}
  {%- set items = ns.items | sort(attribute='key') -%}

  {#- Find the banner outage: the active one, else the next one. -#}
  {%- set pick = namespace(active=-1) -%}
  {%- for i in items -%}
    {%- if pick.active < 0 and i.s is not none and i.e is not none and i.s <= now_ < i.e -%}
      {%- set pick.active = loop.index0 -%}
    {%- endif -%}
  {%- endfor -%}
  {%- set live = pick.active >= 0 -%}
  {#- With a feed problem, the banner shows only an active outage. -#}
  {%- set banner = pick.active if live else (0 if items and not ns.problem else -1) -%}

  {%- if items or ns.problem -%}
  {%- if ns.problem %}

  <ha-alert alert-type="info" title="⚠ {{ L.feed_error }}">
  {{ L.last_good }}: {{ ns.oldest.strftime('%a %-d %b %Y, %H:%M') if ns.oldest else '–' }} · {{ L.list_old }}
  </ha-alert>
  {% endif -%}
  {%- if banner >= 0 -%}
  {%- set b = items[banner] -%}
  {%- if live %}

  <ha-alert alert-type="error" title="🔌 {{ L.now }} · {{ b.loc }}">
  {{ b.s.strftime('%H:%M') }}–{{ b.e.strftime('%H:%M') }} · {{ L.ends_in }} {{ dur(((b.e - now_).total_seconds() // 60) | int) }}
  </ha-alert>
  {% else %}
  {%- set d = daydiff(b.s)|int if b.s else 0 %}

  <ha-alert alert-type="warning" title="⚡ {{ (L.today ~ ', ') if d == 0 and b.s else (L.tomorrow ~ ', ') if d == 1 and b.s else '' }}{{ b.s.strftime('%a %-d %b') if b.s else L.unknown_day }} · {{ span(b) if not b.s else b.s.strftime('%H:%M') ~ '–' ~ (b.e.strftime('%H:%M') if b.e else '?') }}">
  {{ b.loc }}{% if b.s and b.e %} · {{ dur(((b.e - b.s).total_seconds() // 60) | int) }}{% endif %}{% if b.s %} · {{ L.in_day if d == 1 else rel(d) }}{% else %} · {{ b.text }}{% endif %}
  </ha-alert>
  {% endif -%}
  {%- endif -%}
  {%- set rest = namespace(day='') -%}
  {%- set others = items | length - (1 if banner >= 0 else 0) -%}
  {%- if others and banner >= 0 %}

  **{{ L.also }}**
  {% endif -%}
  {%- for i in items -%}
  {%- if loop.index0 != banner -%}
  {%- set label = i.s.strftime('%a %-d %b') if i.s else L.unknown_day -%}
  {%- if label != rest.day %}

  **{{ label }}**
  {% set rest.day = label -%}{%- endif %}
  - {{ i.loc }} · {{ span(i) }}{% if i.s %} · *{{ rel(daydiff(i.s)|int) }}*{% else %} · {{ i.text }}{% endif %}
  {%- endif -%}
  {% endfor %}

  {% if ns.oldest and not ns.problem -%}
  *{{ L.checked }} {{ ns.oldest.strftime('%a %-d %b %Y, %H:%M') }} · elektro-celje.si*
  {%- elif ns.problem -%}
  *{{ L.problem_since }} {{ ns.problem.strftime('%a %-d %b %Y, %H:%M') }} · elektro-celje.si*
  {%- endif %}
  {%- endif %}
```

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

## Contributing

Pull requests are welcome. Run `ruff check .`, `ruff format --check .` and
`pytest -q` before you open one.

## License

MIT License.
