"""Read-only Sentinel MQTT telemetry."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import EconiqCoordinator
from .dashboard import async_register_dashboard

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load entities, then start the explicitly configured telemetry connection."""
    coordinator = EconiqCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_initialize()
    await async_register_dashboard(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Cancel background work and close the socket on removal."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    return True
