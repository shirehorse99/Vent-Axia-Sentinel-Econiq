"""Telemetry connectivity is distinct from motor operating status."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from .entity import EconiqEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([EconiqConnection(entry.runtime_data)])


class EconiqConnection(EconiqEntity, BinarySensorEntity):
    _attr_name = "Telemetry connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "connection")

    @property
    def available(self):
        return True

    @property
    def is_on(self):
        return self.coordinator.connected
