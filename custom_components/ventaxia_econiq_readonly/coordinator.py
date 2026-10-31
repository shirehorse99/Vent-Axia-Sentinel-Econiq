"""Push telemetry lifecycle. This module sends no device commands."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import struct
import time
import uuid
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from datetime import timedelta
from .recovery import RecoveryStatistics

from .const import DOMAIN, CONF_DEVICE_ID, CONF_TLS_IDENTITY, CONF_TLS_PSK
from .protocol import (
    AuthenticationError, ConfigurationError, DEVICE_OUTBOUND, SENSORS,
    device_tls, heartbeat, numeric_reading, open_mqtt, packet,
    parse_publish, structured_reading, subscription_packets,
)

_LOGGER = logging.getLogger(__name__)


class EconiqCoordinator(DataUpdateCoordinator):
    """One connection per entry; no timer polls and no external MQTT broker."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=None, always_update=False)
        self.entry = entry
        self.connected = False
        self.values: dict = {}
        self.attributes: dict = {}
        self.last_telemetry: datetime | None = None
        self.started_at = datetime.now(timezone.utc)
        self.reconnects = 0
        self.received_messages = 0
        self.received_mqtt_bytes = 0
        self.sent_mqtt_bytes = 0
        self.ping_replies = 0
        self.recovery = RecoveryStatistics()
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.statistics")
        self._sample_unsub = None
        self._last_statistics_save = float("-inf")
        self._last_reported = float("-inf")
        self._task: asyncio.Task | None = None
        self._wire = None
        self._last_wire_sent = 0
        self._last_wire_received = 0
        self._mapping = {
            f"{entry.data[CONF_DEVICE_ID]}/{sensor.suffix}": sensor
            for sensor in SENSORS
        }

    async def _async_update_data(self):
        """A HA refresh only returns cached data; it never polls the unit."""
        return self._snapshot()

    def _snapshot(self):
        return {
            "connected": self.connected,
            "values": dict(self.values),
            "attributes": {key: dict(value) for key, value in self.attributes.items()},
            "last_telemetry": self.last_telemetry,
            "started_at": self.started_at,
            "reconnects": self.reconnects,
            "received_messages": self.received_messages,
            "received_mqtt_bytes": self.received_mqtt_bytes,
            "sent_mqtt_bytes": self.sent_mqtt_bytes,
            "ping_replies": self.ping_replies,
            "recovery": self.recovery.current(self.values, self.connected) | self.recovery.stats(datetime.now(timezone.utc)),
        }

    def _notify(self):
        self.async_set_updated_data(self._snapshot())

    async def async_initialize(self):
        saved = await self._store.async_load()
        self.recovery.restore(saved, datetime.now(timezone.utc))

    @callback
    def _sample_recovery(self, now):
        self.recovery.sample(now, self.values, self.connected)
        if time.monotonic() - self._last_statistics_save >= 300:
            self._store.async_delay_save(self.recovery.snapshot, 0)
            self._last_statistics_save = time.monotonic()
        self._notify()

    def start(self):
        """Run only after configuration and platform setup."""
        self._sample_unsub = async_track_time_interval(self.hass, self._sample_recovery, timedelta(minutes=1))
        self._sample_recovery(datetime.now(timezone.utc))
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} telemetry"
        )

    async def async_stop(self):
        if self._sample_unsub:
            self._sample_unsub()
            self._sample_unsub = None
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        await self._store.async_save(self.recovery.snapshot())

    async def _receive(self, wire):
        pending = set(range(1, len(self._mapping) + 1))
        deadline = time.monotonic() + 15
        while True:
            if pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Telemetry subscriptions not acknowledged")
                header, body = await asyncio.wait_for(wire.read(), remaining)
            else:
                header, body = await wire.read()
            self.received_mqtt_bytes += wire.received_bytes - self._last_wire_received
            self._last_wire_received = wire.received_bytes
            self.sent_mqtt_bytes += wire.sent_bytes - self._last_wire_sent
            self._last_wire_sent = wire.sent_bytes
            if header == 0x90:
                if len(body) != 3 or body[2] != 0:
                    raise ValueError("Unexpected subscription response")
                identifier = int.from_bytes(body[:2], "big")
                if identifier not in pending:
                    raise ValueError("Unexpected subscription identifier")
                pending.remove(identifier)
                if not pending:
                    self.connected = True
                    self._notify()
            elif header == 0xD0 and not body:
                self.ping_replies += 1
                self._notify()
            elif header >> 4 == 3:
                topic, payload, identifier = parse_publish(header, body)
                if identifier is not None:
                    await wire.send(packet(0x40, struct.pack("!H", identifier)))
                sensor = self._mapping.get(topic)
                if sensor is None:
                    continue
                self.received_messages += 1
                if sensor.format == "number":
                    value = numeric_reading(payload)
                    reading = (float(value), {}) if value is not None else None
                else:
                    reading = structured_reading(sensor, payload)
                    if reading and sensor.unit:
                        reading = (float(reading[0]), reading[1])
                if reading is None:
                    continue
                value, attributes = reading
                changed = self.values.get(sensor.key) != value or self.attributes.get(sensor.key) != attributes
                self.values[sensor.key] = value
                self.attributes[sensor.key] = attributes
                now = time.monotonic()
                if now - self._last_reported >= 30:
                    self.last_telemetry = datetime.now(timezone.utc)
                    self._last_reported = now
                    changed = True
                if changed:
                    self._notify()
            else:
                raise ValueError("Unexpected MQTT packet")

    async def _session(self):
        data = self.entry.data
        # SSL context construction may load OpenSSL modules; keep it off HA's loop.
        tls = await self.hass.async_add_executor_job(
            device_tls, data[CONF_TLS_IDENTITY], bytes.fromhex(data[CONF_TLS_PSK])
        )
        wire = await open_mqtt(
            data[CONF_HOST], data[CONF_PORT], data.get(CONF_USERNAME, ""),
            data.get(CONF_PASSWORD, ""), f"ha-ro-{uuid.uuid4().hex[:12]}",
            DEVICE_OUTBOUND, tls=tls,
        )
        self._wire = wire
        # A new session must earn fresh readings, including statistical inputs.
        self.values.clear()
        self.attributes.clear()
        self._last_wire_sent = 0
        self._last_wire_received = 0
        workers = []
        try:
            for subscription in subscription_packets(self._mapping):
                await wire.send(subscription)
            workers = [asyncio.create_task(self._receive(wire)), asyncio.create_task(heartbeat(wire))]
            done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
            for worker in done:
                worker.result()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await wire.close()
            self.sent_mqtt_bytes += wire.sent_bytes - self._last_wire_sent
            self.received_mqtt_bytes += wire.received_bytes - self._last_wire_received
            self._wire = None

    async def _run(self):
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                self.connected = False
                self._notify()
                raise
            except (AuthenticationError, ConfigurationError, ssl.SSLError, ValueError) as err:
                self.connected = False
                self._notify()
                # Never print credentials or untrusted payloads, and never guess keys.
                _LOGGER.error("Telemetry stopped (%s); verify credentials, runtime and compatibility", type(err).__name__)
                if isinstance(err, (AuthenticationError, ssl.SSLError)):
                    self.entry.async_start_reauth(self.hass)
                return
            except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
                self.connected = False
                self.reconnects += 1
                self._notify()
                _LOGGER.warning("Telemetry interrupted (%s); retrying in 30 seconds", type(err).__name__)
                await asyncio.sleep(30)
