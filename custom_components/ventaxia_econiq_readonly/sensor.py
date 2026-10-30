"""Reported telemetry and local communication diagnostics."""
from homeassistant.components.sensor import (
    SensorEntity, SensorDeviceClass, SensorStateClass,
)
from homeassistant.const import EntityCategory

from .entity import EconiqEntity
from .protocol import SENSORS

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [EconiqSensor(coordinator, sensor) for sensor in SENSORS]
        + [EconiqDiagnostic(coordinator, key, name, device_class, unit, state_class)
           for key, name, device_class, unit, state_class in (
               ("last_telemetry", "Last telemetry received", SensorDeviceClass.TIMESTAMP, None, None),
               ("started_at", "Integration started at", SensorDeviceClass.TIMESTAMP, None, None),
               ("reconnects", "Reconnect attempts this run", None, None, None),
               ("received_messages", "Telemetry messages received this run", None, None, None),
               ("received_mqtt_bytes", "MQTT bytes received this run", SensorDeviceClass.DATA_SIZE, "B", SensorStateClass.TOTAL_INCREASING),
               ("sent_mqtt_bytes", "MQTT bytes sent this run", SensorDeviceClass.DATA_SIZE, "B", SensorStateClass.TOTAL_INCREASING),
               ("ping_replies", "Keepalive replies this run", None, None, None),
           )]
    )


class EconiqSensor(EconiqEntity, SensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor.key)
        self._sensor = sensor
        self._attr_name = sensor.name
        self._attr_native_unit_of_measurement = sensor.unit
        self._attr_device_class = sensor.device_class
        if sensor.format in ("number", "wifi"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if sensor.format in ("faults", "warnings", "notices", "wifi", "regulation"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if sensor.key in ("co2", "filter_1_remaining", "filter_2_remaining"):
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self):
        return super().available and self._key in self.coordinator.values

    @property
    def native_value(self):
        return self.coordinator.values.get(self._key)

    @property
    def extra_state_attributes(self):
        return self.coordinator.attributes.get(self._key, {})


class EconiqDiagnostic(EconiqEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, name, device_class, unit, state_class):
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class

    @property
    def available(self):
        return self._key != "last_telemetry" or self.coordinator.last_telemetry is not None

    @property
    def native_value(self):
        return getattr(self.coordinator, self._key)
