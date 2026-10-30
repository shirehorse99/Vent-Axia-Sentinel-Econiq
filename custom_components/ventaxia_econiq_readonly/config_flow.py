"""Configure an existing Wi-Fi/TLS-PSK connection without pairing writes."""
from __future__ import annotations

import re
import ssl

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_DEVICE_ID, CONF_TLS_IDENTITY, CONF_TLS_PSK,
    CONF_OTHER_CLIENTS_STOPPED,
)

PASSWORD = selector.TextSelector({"type": selector.TextSelectorType.PASSWORD})


def validate(data):
    """Validate locally; this never opens a network connection."""
    if not getattr(ssl, "HAS_PSK", False):
        return "psk_unsupported"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,253}", data[CONF_HOST]):
        return "invalid_host"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", data[CONF_DEVICE_ID]):
        return "invalid_device_id"
    identity = data[CONF_TLS_IDENTITY]
    key = data[CONF_TLS_PSK]
    if not identity or "\0" in identity or len(identity.encode()) > 256:
        return "invalid_credentials"
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}){1,256}", key) or not any(bytes.fromhex(key)):
        return "invalid_credentials"
    if any("\0" in data.get(name, "") for name in (CONF_USERNAME, CONF_PASSWORD)):
        return "invalid_credentials"
    if not data.get(CONF_OTHER_CLIENTS_STOPPED):
        return "other_clients_running"
    return None


class EconiqConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Store supplied credentials; never recover keys by writing to the unit."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if error := validate(user_input):
                errors["base"] = error
            else:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                data = dict(user_input)
                data.pop(CONF_OTHER_CLIENTS_STOPPED)
                return self.async_create_entry(
                    title=f"Sentinel {data[CONF_DEVICE_ID]}", data=data
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=8883): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_TLS_IDENTITY): PASSWORD,
                vol.Required(CONF_TLS_PSK): PASSWORD,
                vol.Optional(CONF_USERNAME, default=""): str,
                vol.Optional(CONF_PASSWORD, default=""): PASSWORD,
                vol.Required(CONF_OTHER_CLIENTS_STOPPED, default=False): bool,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            if error := validate(dict(entry.data) | user_input):
                errors["base"] = error
            else:
                data = dict(user_input)
                data.pop(CONF_OTHER_CLIENTS_STOPPED)
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_TLS_IDENTITY): PASSWORD,
                vol.Required(CONF_TLS_PSK): PASSWORD,
                vol.Required(CONF_OTHER_CLIENTS_STOPPED, default=False): bool,
            }), errors=errors,
        )
