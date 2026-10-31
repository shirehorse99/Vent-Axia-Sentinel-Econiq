"""Isolated protocol tests: no Home Assistant installation or live sockets."""
import asyncio
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_components/ventaxia_econiq_readonly'))
import protocol as p


class Writer:
    def __init__(self):
        self.data = bytearray()
    def write(self, data):
        self.data.extend(data)
    async def drain(self):
        pass
    def close(self):
        pass
    async def wait_closed(self):
        pass


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_and_last_will_cannot_reach_device(self):
        writer = Writer()
        wire = p.Wire(asyncio.StreamReader(), writer, p.DEVICE_OUTBOUND)
        with self.assertRaises(PermissionError):
            await wire.send(p.packet(0x30, b'anything'))
        self.assertEqual(writer.data, b'')
        with patch.object(p.asyncio, 'open_connection') as connect:
            with self.assertRaises(PermissionError):
                await p.open_mqtt('unused', 8883, '', '', 'test', p.DEVICE_OUTBOUND, will=('topic', 'payload'))
            connect.assert_not_called()

    async def test_connect_has_no_will_and_advertises_sixty_seconds(self):
        reader = asyncio.StreamReader()
        reader.feed_data(p.connect_packet('synthetic-client', '', ''))
        header, body = await p.read_packet(reader)
        self.assertEqual(header, 0x10)
        self.assertEqual(body[7] & 6, 2)
        self.assertEqual(struct.unpack_from('!H', body, 8)[0], 60)

    async def test_fragmented_multibyte_length_packet(self):
        reader = asyncio.StreamReader()
        data = p.packet(0x30, b'x' * 300)
        async def feed():
            for byte in data:
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(0)
        feeder = asyncio.create_task(feed())
        self.assertEqual(await p.read_packet(reader), (0x30, b'x' * 300))
        await feeder

    async def test_periodic_ping_survives_busy_qos_zero_traffic(self):
        now = [100.0]
        reader, writer = asyncio.StreamReader(), Writer()
        with patch.object(p.time, 'monotonic', side_effect=lambda: now[0]):
            wire = p.Wire(reader, writer, p.DEVICE_OUTBOUND)
            async def tick(_):
                now[0] += 1
                wire.last_tx = now[0]
                if wire.pending_ping is not None:
                    reader.feed_data(b'\xd0\0')
                    await wire.read()
                if now[0] >= 240:
                    raise asyncio.CancelledError()
            with patch.object(p.asyncio, 'sleep', side_effect=tick):
                with self.assertRaises(asyncio.CancelledError):
                    await p.heartbeat(wire)
        self.assertEqual(writer.data, b'\xc0\0' * 3)
        self.assertEqual(wire.sent_bytes, 6)
        self.assertEqual(wire.received_bytes, 6)

    async def test_unanswered_ping_is_a_real_timeout(self):
        now = [100.0]
        with patch.object(p.time, 'monotonic', side_effect=lambda: now[0]):
            wire = p.Wire(asyncio.StreamReader(), Writer(), p.DEVICE_OUTBOUND)
            async def tick(_):
                now[0] += 1
            with patch.object(p.asyncio, 'sleep', side_effect=tick):
                with self.assertRaises(TimeoutError):
                    await p.heartbeat(wire)
            self.assertEqual(wire.writer.data, b'\xc0\0')
            self.assertLess(now[0] - 100, 60)

    async def test_each_subscription_is_one_exact_telemetry_topic(self):
        mapping = {f'synthetic/{s.suffix}': s for s in p.SENSORS}
        packets = list(p.subscription_packets(mapping))
        self.assertEqual(len(packets), 40)
        for expected, data in zip(mapping, packets):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            header, body = await p.read_packet(reader)
            self.assertEqual(header, 0x82)
            length = int.from_bytes(body[2:4], 'big')
            self.assertEqual(body[4:4+length].decode(), expected)
            self.assertEqual(body[4+length:], b'\0')
            self.assertFalse(any(x in expected for x in ('+', '#')))

    def test_unknown_fault_bits_are_reported_not_cleared(self):
        count, attrs = p.status_reading('faults', b'1048576')
        self.assertEqual(count, '1')
        self.assertEqual(attrs['unknown_bits_hex'], '0x00100000')
        self.assertEqual(attrs['status'], 'Reported')
        self.assertIsNone(p.status_reading('faults', b'[]'))

    def test_presets_and_override_source_are_not_guessed(self):
        self.assertEqual(p.preset_reading(b'{"ps":1,"prop":0.66}')[0], 'Low')
        sensor = next(s for s in p.SENSORS if s.key == 'override')
        name, attrs = p.structured_reading(sensor, b'{"ot":3,"os":130,"treq":"00:20:00","trem":"12:00:00"}')
        self.assertEqual(name, 'Extract humidity')
        self.assertEqual(attrs['reported_source_id'], 130)
        self.assertEqual(attrs['requested_seconds'], 1200)
        self.assertNotIn('expiry', attrs)
        self.assertEqual(p.preset_reading(b'{"ps":123}')[0], 'Unknown code 123')

    def test_unverified_units_and_malformed_values_are_not_fabricated(self):
        for sensor in p.SENSORS:
            if 'airflow' in sensor.key:
                self.assertIsNone(sensor.unit)
        for value in (b'nan', b'inf', b'-inf', b'{}', b'\xff'):
            self.assertIsNone(p.numeric_reading(value))
        self.assertEqual(p.numeric_reading(b'18.9'), '18.9')
