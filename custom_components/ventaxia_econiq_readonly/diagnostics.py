"""Export local counters and availability without network access or secrets."""
async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "connected": coordinator.connected,
        "reconnects_this_run": coordinator.reconnects,
        "last_telemetry": coordinator.last_telemetry.isoformat() if coordinator.last_telemetry else None,
        "mqtt_bytes_received": coordinator.received_mqtt_bytes,
        "mqtt_bytes_sent": coordinator.sent_mqtt_bytes,
        "telemetry_messages_received": coordinator.received_messages,
        "ping_replies": coordinator.ping_replies,
        "reported_sensor_keys": sorted(coordinator.values),
        "board_temperature": "No verified telemetry endpoint",
        "counter_scope": "MQTT framing only; excludes TLS/TCP/Wi-Fi overhead. Resets on reload.",
    }
