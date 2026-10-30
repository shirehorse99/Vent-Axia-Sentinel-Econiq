"""Coordinator lifecycle with minimal HA stubs; not a real HA loading test."""
import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

COMPONENT = Path(__file__).resolve().parents[1] / 'custom_components/ventaxia_econiq_readonly'
package = types.ModuleType('_econiq_candidate')
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package

class FakeDataCoordinator:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass
    def async_set_updated_data(self, data):
        self.data = data

stubs = {name: types.ModuleType(name) for name in (
    'homeassistant', 'homeassistant.config_entries', 'homeassistant.const',
    'homeassistant.core', 'homeassistant.helpers', 'homeassistant.helpers.update_coordinator',
)}
stubs['homeassistant.config_entries'].ConfigEntry = object
stubs['homeassistant.core'].HomeAssistant = object
for key in ('HOST','PORT','USERNAME','PASSWORD'):
    setattr(stubs['homeassistant.const'], 'CONF_'+key, key.lower())
stubs['homeassistant.helpers.update_coordinator'].DataUpdateCoordinator = FakeDataCoordinator
with patch.dict(sys.modules, stubs):
    m = importlib.import_module('_econiq_candidate.coordinator')
    p = importlib.import_module('_econiq_candidate.protocol')

class Hass:
    async def async_add_executor_job(self, function, *args):
        return function(*args)

class Entry:
    data = {'device_id':'synthetic', 'host':'unused', 'port':8883,
            'tls_identity':'synthetic-identity', 'tls_psk_hex':'0123456789abcdef'}
    reauths = 0
    def async_create_background_task(self, hass, target, name):
        return asyncio.create_task(target, name=name)
    def async_start_reauth(self, hass):
        self.reauths += 1

class Writer:
    def __init__(self, reader):
        self.reader, self.closed = reader, False
        self.packets = []
    def write(self, data):
        self.packets.append(data)
        if data[0] == 0x82:
            # These subscriptions are short enough for a one-byte Remaining Length.
            identifier = data[2:4]
            self.reader.feed_data(p.packet(0x90, identifier+b'\0'))
            if b'/mdet/pwr' in data:
                self.reader.feed_data(p.packet(0x30, p.mqtt_string('synthetic/mdet/pwr')+b'33.5'))
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        pass

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_data_and_unload_close_all_workers_without_publishing(self):
        reader = asyncio.StreamReader()
        writer = Writer(reader)
        wire = p.Wire(reader, writer, p.DEVICE_OUTBOUND)
        async def connect(*args, **kwargs):
            self.assertEqual(args[5], p.DEVICE_OUTBOUND)
            self.assertNotIn('will', kwargs)
            return wire
        coordinator = m.EconiqCoordinator(Hass(), Entry())
        with patch.object(m, 'open_mqtt', side_effect=connect), patch.object(m, 'device_tls', return_value=object()):
            coordinator.start()
            for _ in range(400):
                if coordinator.connected and coordinator.values.get('system_power') == 33.5:
                    break
                await asyncio.sleep(0)
            self.assertTrue(coordinator.connected)
            self.assertEqual(coordinator.values['system_power'], 33.5)
            self.assertIsNotNone(coordinator.last_telemetry)
            self.assertGreater(coordinator.received_mqtt_bytes, 0)
            await coordinator.async_stop()
        self.assertTrue(writer.closed)
        self.assertIsNone(coordinator._wire)
        self.assertFalse(coordinator.connected)
        self.assertEqual(sum(data[0]>>4 == 8 for data in writer.packets), 22)
        self.assertTrue(all(data[0]>>4 in p.DEVICE_OUTBOUND for data in writer.packets))
        self.assertEqual(writer.packets[-1], b'\xe0\0')
        workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                   and getattr(t.get_coro(), '__name__', '') in ('_receive','heartbeat')]
        self.assertEqual(workers, [])

    async def test_auth_failure_stops_and_requests_reauth_without_retries(self):
        async def reject(*args, **kwargs):
            raise p.AuthenticationError()
        entry = Entry()
        coordinator = m.EconiqCoordinator(Hass(), entry)
        with patch.object(m, 'open_mqtt', side_effect=reject) as connect, patch.object(m, 'device_tls', return_value=object()):
            coordinator.start()
            await coordinator._task
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(entry.reauths, 1)
        self.assertEqual(coordinator.reconnects, 0)
        self.assertFalse(coordinator.connected)
