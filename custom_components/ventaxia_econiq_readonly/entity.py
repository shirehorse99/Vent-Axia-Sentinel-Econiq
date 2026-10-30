"""Common entity identity and availability."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_ID


class EconiqEntity(CoordinatorEntity):
    """Entities share the controller device, without control services."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        device_id = coordinator.entry.data[CONF_DEVICE_ID]
        self._key = key
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"Sentinel {device_id}",
            manufacturer="Vent-Axia",
            model="MQTT/TLS-PSK controller",
        )

    @property
    def available(self):
        return super().available and self.coordinator.connected
