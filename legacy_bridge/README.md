# Standalone read-only MQTT bridge (legacy deployment)

This directory preserves the separate sensor-only bridge used before migration to the native HACS integration. It is not required by HACS, is not started by the native integration, and must not run alongside another client for the same unit. The native integration connects directly and does not use this external-broker state-restoration path.

Version **0.4.2** retains validated states and JSON attributes on the **local Home Assistant MQTT broker**. An HA MQTT entity resubscription receives the most recently reported values even when a unit publishes them infrequently. Empty attribute dictionaries replace old keys. Availability remains governed by the bridge's device session and broker last will; retained values are not a claim of current availability.

Before each new device session, the bridge marks itself offline and clears retained telemetry/attribute/last-reading caches. Fresh readings repopulate the cache via the existing 40 exact subscriptions. No control topic, device PUBLISH, additional polling, firmware action or device setting is introduced. Device keepalive remains 60 seconds with 45-second pings.

This is source for an existing/manual bridge deployment, not a second recommended install path for a new HACS user. Use the [native integration setup guide](../docs/setup.md) for new trials. The JSON-formatted `config.yaml` contains empty credential placeholders only. Installation credentials belong outside this repository. The optional `--validate --options /private/path/options.json` validates configuration without contacting either endpoint; running without `--validate` connects to the explicitly configured endpoints.

Run tests from the repository root:

```sh
python -B -m unittest discover -s legacy_bridge -p test_bridge.py
```

Tests cover retained replay for a new subscriber, replacement of old attributes, cache invalidation on new sessions, payload handling, heartbeat timing, exact subscriptions and device PUBLISH blocking. Live replay can be checked by subscribing a fresh read-only client to the local broker; a complete HA restart is unnecessary and may disrupt unrelated integrations. Source and tests do not establish thermal safety or compatibility with every controller.
