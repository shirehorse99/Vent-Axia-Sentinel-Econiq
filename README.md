# Vent-Axia Sentinel Econiq — read-only Home Assistant integration

Experimental HACS candidate, version 0.2.0. Prepared for [shirehorse99/Vent-Axia-Sentinel-Econiq](https://github.com/shirehorse99/Vent-Axia-Sentinel-Econiq).

This connects directly to the unit’s built-in MQTT broker using its saved TLS-PSK credentials. It requires no external MQTT broker, external temperature sensor, cloud account or subscription. It exposes sensors and telemetry connectivity only.

## Compatibility

The telemetry protocol and authentication were verified using a Kinetic Advance S enclosure with a replacement controller advertising Sentinel Econiq. Its reported firmware was ESP32 1.3.12, MVHR 1.12.4 and controller 1.13.0. CI includes passing Home Assistant 2026.10.4 setup/unload and statistics-persistence tests with synthetic data, plus isolated tests, HACS validation and hassfest. The portable dashboard has been checked live against the standalone bridge. A native connection trial on physical hardware remains separate from these checks.

This is **not universal support for every Vent-Axia model**. Legacy Kinetic Advance Wi-Fi modules can use a different raw JSON protocol. An enclosure’s original model name does not establish controller compatibility. Missing CO₂ or filter-life readings are not fabricated; those entities are disabled by default.

## Installation

For a custom-repository trial, add this repository’s URL in HACS → Custom repositories, category Integration. Download it, restart Home Assistant, then add “Vent-Axia Sentinel Econiq (read only)” under Settings → Devices & services.

Manual installation: copy `custom_components/ventaxia_econiq_readonly` into Home Assistant’s `custom_components` directory and restart Home Assistant. Home Assistant 2025.2 or later is required, with Python 3.13+ and a PSK-enabled OpenSSL build. The configuration form checks the PSK capability without contacting the unit.

Configure the unit hostname/IP, TLS port (normally 8883), device ID/topic prefix, existing saved TLS identity and nonzero hexadecimal TLS key. Device MQTT username/password are usually blank. The TLS identity is used as supplied; it is not replaced with a hardcoded name or decoded from hex. A home Wi-Fi password or app PIN does not supply the TLS key. Credentials are stored in Home Assistant’s config entry, so protect Home Assistant and its backups.

**Stop the previous add-on/integration before completing setup.** The form requires acknowledgement. Setup validates the format locally; saving starts the live connection. It does not discover credentials, pair Bluetooth, change a PIN, upload firmware or configure Wi-Fi.

## Portable dashboard and connection guide

The [connection and credential guide](docs/setup.md) explains which details come from the unit label, app and router, how to use credentials already saved by a paired app, and the limits of the supported iPhone backup recovery tool. No physical access or re-pairing is required by the integration itself, but an existing working app pairing is required to obtain saved credentials. Do not post credentials or phone backups in issues.

The [portable dashboard guide](docs/dashboard.md) provides a registry-based strategy with Overview, Statistics, Diagnostics and Maintenance tabs. It resolves renamed entities and multiple compatible units without personal entity IDs, addresses or recorded baselines. It includes locally calculated recovery statistics with one-minute sampling and 24-hour persistence; these calculations send no additional requests to the unit.

Additional reported data includes bypass position/mode, frost state, air-quality state, motor power in W, motor/unit runtimes in hours, filter types and maintenance dates, service interval in months, model metadata and Wi-Fi firmware. Missing values remain unavailable. The filter-interval unit and raw frost power/usage units are not yet verified.

## Data and traffic

There are 40 exact telemetry subscriptions, sent once per connection. There are no wildcard or control topics. The unit pushes sensor readings; this integration does not poll them or set their publication rate. Disabling an entity hides it in HA but does not currently remove its subscription.

MQTT CONNECT advertises a 60-second keepalive. A two-byte PINGREQ is sent every 45 seconds, allowing a 10-second reply timeout. Its PINGRESP is also two bytes; TLS/TCP/Wi-Fi add overhead. Unchanged numeric readings are not needlessly republished to HA, and the last-telemetry timestamp is updated at most once per 30 seconds on real valid readings. Network failures retry after 30 seconds. Authentication/TLS failures stop rather than guess keys; incompatible protocol responses also stop.

The device socket permits only CONNECT, SUBSCRIBE, PUBACK, PINGREQ and DISCONNECT. PUBLISH is blocked, and the connection has no last will. There are no fan, select, button, climate or switch entities and no control services. Communication still consumes some controller resources; this is not a zero-load or hardware-safety guarantee.

## Sensors and limitations

Reported fan RPM, three air temperatures, intake/extract humidity, total electrical power, raw demanded/measured airflow, reported preset, override cause, regulation type, RSSI and fault/warning/notice flags. CO₂ and filter-life entities are available where the unit supplies values.

Airflow units remain unverified across regulation modes, so raw flow values are not labelled L/s, m³/h or percent. The verified enum is Off / Low / Normal / Boost / Purge / None / Maximum; “Quiet” has not been proven equivalent to Low on every controller. Fault attributes preserve raw hexadecimal masks, known code numbers and unknown bits without inventing fault descriptions. Override start time is not presented as an expiry countdown.

Local diagnostics include connection state, reconnect attempts, timestamps, received-message and MQTT-byte counters, and keepalive replies. Counters reset on reload; byte counts include MQTT framing but exclude TLS/TCP/Wi-Fi overhead. They measure communication, **not CPU utilisation or temperature**. Downloaded diagnostics omit host, device ID, credentials and raw payloads.

## Electronics temperature

No board/CPU temperature endpoint has been verified. Air-stream temperatures and absence of fault flags do not prove the electronics are cool. This integration does not claim to detect or prevent board overheating. There is no external-sensor dependency; optional environmental alerts belong in the user’s own Home Assistant configuration.

Vent-Axia publishes a +40°C maximum ambient operating temperature for the Econiq range in its [specification brochure](https://www.vent-axia.com/sites/default/files/2024-02/vent-axia_specification_brochure..pdf). Confirm the applicable limit for any replacement board and installation with the manufacturer. Reducing network traffic does not make an excessive attic temperature acceptable.

## Migration and energy

Keep the current working bridge until this candidate has passed validation. To trial the native integration, stop that bridge first. New native entities have different identities from the MQTT entities; history does not automatically migrate. Update dashboards, energy helpers and alerts to the new entity IDs only after confirming their readings. Do not delete old history as part of the trial.

Optional energy estimates can use HA’s Integral helper on the reported W sensor, followed by daily/monthly Utility Meter helpers. These are calculations in Home Assistant and add no device traffic. No tariff/cost assumptions are included.

## Development and release checks

Run `python -B -m unittest discover -s tests` for isolated protocol, recovery-statistics, credential-recovery and coordinator-lifecycle checks (the latter use HA stubs). Tests use synthetic payloads and fake streams; they do not connect to a unit. Run `node tests/test_dashboard.cjs` for portable dashboard fixtures. CI also runs actual Home Assistant setup/unload smoke tests using synthetic readings, HACS validation and hassfest. The repository has not been submitted to the HACS default catalogue. A native hardware connection and reauthentication trial is required before describing this candidate as release-validated.

To remove it, delete its config entry, then remove the repository using HACS and restart Home Assistant. Unloading cancels the background task and closes the MQTT socket; it does not change the MVHR’s operating settings.

## Acknowledgements

Protocol observations were compared with [JosyBan/ventaxia_ha](https://github.com/JosyBan/ventaxia_ha), [issue 34](https://github.com/JosyBan/ventaxia_ha/issues/34), and [bvolders/ha-ventaxia-econiq](https://github.com/bvolders/ha-ventaxia-econiq). No app APK, phone backup, private logs, recovered credentials or third-party control code is included.
