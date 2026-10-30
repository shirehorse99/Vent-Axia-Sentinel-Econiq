# Candidate validation

2026-10-30: eleven isolated checks pass: nine MQTT framing/parsing/safety checks and two coordinator lifecycle checks using minimal Home Assistant stubs. The lifecycle checks verify telemetry push, authentication-failure stopping, background-task cancellation and clean disconnect. These do not replace a real HA setup/unload test. All candidate Python files compile and JSON files parse.

The required runtime APIs were checked against Home Assistant 2025.2.0 source: ConfigEntry background tasks and reauthentication helpers, and DataUpdateCoordinator config_entry support. HACS repository structure, manifest fields and bundled brand assets follow the current HACS/HA documentation.

The separately deployed standalone bridge shares this MQTT framing and parser implementation. Its 60-second CONNECT keepalive / 45-second ping timing remained connected for more than 21 minutes with fresh telemetry and zero reconnects at the final dashboard observation. That test was on the known replacement board; it is not validation of this native wrapper on all Econiq models.

GitHub Actions passed the eleven tests on Python 3.13, hassfest and all ten HACS checks. Repository description/topics were completed and the validation run then passed. Run: https://github.com/shirehorse99/Vent-Axia-Sentinel-Econiq/actions/runs/41138642958.

Before release: trial actual HA configuration, authentication, reauthentication, unload/reload and removal, with the standalone bridge stopped. Review compatibility reports before adding further models. The candidate source is committed to the owner’s GitHub repository; it has not been installed as a second client or submitted to the HACS default catalogue.

No verified CPU/board temperature endpoint is implemented. Fault-free communications and local traffic counters do not demonstrate thermal safety. No external sensor is required.
