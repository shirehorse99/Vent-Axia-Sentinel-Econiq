"""Serve the bundled strategy; load it as a normal Lovelace module resource."""
from __future__ import annotations
import asyncio
from pathlib import Path
from homeassistant.components.http import StaticPathConfig
from .const import DOMAIN

DASHBOARD_URL = "/ventaxia_econiq_readonly/dashboard.js"

async def async_register_dashboard(hass):
    """Register once without adding global early-loading JavaScript."""
    if getattr(hass, "http", None) is None:
        return False
    data = hass.data.setdefault(DOMAIN, {})
    lock = data.setdefault("dashboard_lock", asyncio.Lock())
    async with lock:
        if data.get("dashboard_registered"):
            return True
        await hass.http.async_register_static_paths([
            StaticPathConfig(DASHBOARD_URL, str(Path(__file__).parent / "frontend" / "dashboard.js"), False)
        ])
        data["dashboard_registered"] = True
    return True
