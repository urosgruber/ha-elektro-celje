<!--
{% if installed %}
## Elektro Celje Obvestila o izklopih
{% else %}
# Elektro Celje Obvestila o izklopih
{% endif %}

![Project Maintenance][maintenance-shield]

{% if installed %}
![Project Maintenance][maintenance-shield]
{% endif %}

{% if version %}
**Version: 1.0.0**
{% endif %}
-->

**This is a custom integration for Home Assistant.**

# Elektro Celje Power Outage Notification Integration for Home Assistant

## Overview

The Elektro Celje Power outage notification integration for Home Assistant allows users to track planned maintenance power outages for specific transformer power stations in the Elektro Celje power grid provider.

## Installation

To install the integration using HACS (Home Assistant Community Store):

1. Make sure you have HACS installed.
2. Navigate to HACS -> Integrations.
3. Add the following repository to your HACS custom repositories: https://github.com/urosgruber/ha-elektro-celje.git.
4. Search for "Elektro Celje Power" and download the integration.
5. Restart your Home Assistant.

## Configuration

Add the following YAML code to your `configuration.yml` file:

```yaml
binary_sensor:
  - platform: elektro_celje
    name: Name your sensor
    region: Celje
    search_station: the name of the station
```

## Usage

The integration provides a binary sensor that can be used on any Home Assistant dashboard. Create automations to receive notifications when a power outage is planned.

### Additional attributes include:

- `working_day`: Description of the actual day and time maintenance will be run.
- `published_date`: Date when maintenance is planned.

## Troubleshooting

If you encounter any issues, please open a new issue on GitHub.

## Contributing

Users are welcome to provide additional changes and improvements. Don't forget to star the repository if you find it useful! ⭐

## License

This integration is licensed under the MIT License.
