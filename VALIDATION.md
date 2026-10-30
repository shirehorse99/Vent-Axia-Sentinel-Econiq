# Candidate validation

2026-10-30: eleven isolated checks pass: nine MQTT framing/parsing/safety checks and two coordinator lifecycle checks using minimal Home Assistant stubs. The lifecycle checks verify telemetry push, authentication-failure stopping, background-task cancellation and clean disconnect. These do not replace a real HA setup/unload test. All candidate Python files compile and JSON files parse.

The required runtime APIs were checked against Home Assistant 2025.2.0 source: ConfigEntry background tasks and reauthentication helpers, and DataUpdateCoordinator config_entry support. HACS repository structure, manifest fields and bundled brand assets follow the current HACS/HA documentation.

A separate hardware trial verified telemetry through the standalone MQTT bridge. The native integration shares its MQTT framing and parser. Native hardware setup and reauthentication are still pending.

Before public release: run HACS validation and hassfest in the target repository, then trial actual HA configuration, authentication, reauthentication, unload/reload and removal, with the standalone bridge stopped. Review compatibility reports before adding further models. This candidate has not been published or installed as a second client.

No verified CPU/board temperature endpoint is implemented. Fault-free communications and local traffic counters do not demonstrate thermal safety. No external sensor is required.
