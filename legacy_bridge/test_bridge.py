"""Offline safety/protocol checks. No sockets or live unit required."""
import asyncio
import json
from pathlib import Path
import ssl
import struct
import unittest
from unittest.mock import patch

import bridge as b


class Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def options():
    o = json.loads(Path(__file__).with_name('config.yaml').read_text())['options']
    o.update(device_host='unit.test',mqtt_host='ha.test',device_id='synthetic',tls_identity='synthetic-identity')
    o['tls_psk_hex'] = '0123456789abcdef'  # Synthetic test key, never sent over a socket.
    return o


class ConfigurationTests(unittest.TestCase):
    def test_unavailable_and_malformed_keys_fail(self):
        for key in ('', '0000000000000000', '0000', 'zirconia', 'abc', '01 23'):
            with self.subTest(key=key), self.assertRaises(b.ConfigurationError):
                b.validate_options(options() | {'tls_psk_hex': key})

    def test_key_is_raw_bytes_and_configuration_rejects_topic_injection(self):
        self.assertEqual(b.validate_options(options()), bytes.fromhex('0123456789abcdef'))
        for extra in ({'device_id': '#'}, {'mqtt_host': 'unit.test'},
                      {'device_port': True}, {'tls_identity': 'a\0b'}):
            with self.subTest(extra=extra), self.assertRaises(b.ConfigurationError):
                b.validate_options(options() | extra)

    def test_discovery_has_only_sensor_state_fields(self):
        for sensor in b.SENSORS:
            d = b.discovery(sensor, 'test-device', 'test/state')
            self.assertNotIn('expire_after', d)  # Unchanged push values remain valid while connected.
            self.assertNotIn('command_topic', d)
            self.assertNotIn('unit_of_measurement', d) if not sensor.unit else None
            self.assertFalse(sensor.suffix.endswith('/wr'))
            self.assertFalse(any(x in sensor.suffix for x in ('+', '#')))

    def test_numeric_payloads_reject_nonfinite_and_json(self):
        for payload in (b'nan', b'inf', b'-inf', b'{"value": 23}', b'\xff', b'1'*129):
            self.assertIsNone(b.numeric_reading(payload))
        self.assertEqual(b.numeric_reading(b'-12.5'), '-12.5')

    def test_preset_codes_are_explicit_and_do_not_use_airflow_ratios(self):
        for code, expected in ((1,'Low'),(2,'Normal'),(3,'Boost'),(4,'Purge'),(19,'Unknown code 19')):
            self.assertEqual(b.preset_reading(json.dumps({'ps':code,'prop':0.66}).encode())[0], expected)
        for payload in (b'{"ps":true}',b'{"ps":"2"}',b'[]',b'{"prop":0.66}',b'broken'):
            self.assertIsNone(b.preset_reading(payload))

    def test_diagnostics_have_no_command_topics_or_false_connection_availability(self):
        entries = b.diagnostic_discovery('unit','local/unit')
        self.assertEqual(entries[0][2]['state_topic'], 'local/unit/availability')
        self.assertNotIn('availability_topic', entries[0][2])
        self.assertEqual(entries[1][2]['device_class'], 'timestamp')
        self.assertTrue(all('command_topic' not in entry[2] for entry in entries))

    def test_fault_masks_preserve_high_and_unknown_bits(self):
        count, attrs = b.status_reading('faults', b'-2147483643')
        self.assertEqual(count, '3')
        self.assertEqual(attrs['codes'], ['F01','F03','F32'])
        self.assertEqual(attrs['raw_hex'], '0x80000005')
        count, attrs = b.status_reading('faults', b'256')
        self.assertEqual(count, '1')
        self.assertEqual(attrs['codes'], [])
        self.assertEqual(attrs['unknown_bits_hex'], '0x00000100')
        self.assertEqual(b.status_reading('warnings', b'0x00100001')[1]['codes'], ['W01','W21'])
        self.assertEqual(b.status_reading('notices', b'16')[1]['codes'], ['N05'])

    def test_unreported_fault_status_is_not_falsely_clear(self):
        for payload in (b'',b'unknown',b'[]',b'1.5',b'4294967296',b'-2147483649',b'NaN'):
            self.assertIsNone(b.status_reading('faults', payload))
        self.assertEqual(b.status_reading('faults', b'0'), ('0', {
            'raw_mask':0,'raw_hex':'0x00000000','codes':[], 'unknown_bits_hex':'0x00000000','status':'Clear'}))

    def test_override_source_is_not_a_mode_or_remaining_timestamp(self):
        sensor = next(s for s in b.SENSORS if s.format=='override')
        state, attrs = b.structured_reading(sensor, b'{"ot":3,"os":130,"treq":"00:15:00","trem":"2026-10-30T12:00:00"}')
        self.assertEqual(state,'Extract humidity')
        self.assertEqual(attrs['reported_source_id'],130)
        self.assertEqual(attrs['requested_seconds'],900)
        self.assertEqual(attrs['reported_started_at'],'2026-10-30T12:00:00')
        self.assertNotIn('remaining_seconds',attrs)

    def test_wifi_reading_excludes_network_identifiers(self):
        sensor=next(s for s in b.SENSORS if s.format=='wifi')
        self.assertEqual(b.structured_reading(sensor,b'{"rssi":-62,"ssid":"private-name","ipaddr":"192.0.2.10"}'),('-62',{}))
        self.assertIsNone(b.structured_reading(sensor,b'{"rssi":"invalid"}'))

    def test_invalid_and_future_codes_are_safe(self):
        sensor=next(s for s in b.SENSORS if s.format=='override')
        self.assertIsNone(b.structured_reading(sensor,b'{"ot":true}'))
        self.assertEqual(b.structured_reading(sensor,b'{"ot":230}')[0],'Unknown code 230')
        self.assertIsNone(b.preset_reading(b'{"ps":9999}'))
        self.assertEqual(b.preset_reading(b'{"ps":2,"prop":NaN}')[0],'Normal')

    def test_in_memory_tls_psk_handshake(self):
        # Exercises real OpenSSL PSK negotiation without creating a socket.
        key = b.validate_options(options())
        client_ctx = b.device_tls('zirconia', key)
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.minimum_version = server_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        server_ctx.set_ciphers('PSK-AES128-CBC-SHA')
        identities = []

        def lookup(identity):
            identities.append(identity)
            return key if identity == 'zirconia' else b''

        server_ctx.set_psk_server_callback(lookup)
        ci, co, si, so = (ssl.MemoryBIO() for _ in range(4))
        client = client_ctx.wrap_bio(ci, co, server_side=False)
        server = server_ctx.wrap_bio(si, so, server_side=True)
        completed = set()
        for _ in range(20):
            for name, endpoint in (('client', client), ('server', server)):
                if name not in completed:
                    try:
                        endpoint.do_handshake()
                        completed.add(name)
                    except ssl.SSLWantReadError:
                        pass
            si.write(co.read())
            ci.write(so.read())
            if len(completed) == 2:
                break
        self.assertEqual(completed, {'client', 'server'})
        self.assertEqual(identities, ['zirconia'])
        self.assertEqual(client.cipher()[0], 'PSK-AES128-CBC-SHA')
        self.assertEqual(client.version(), 'TLSv1.2')
        client.write(b'offline telemetry test')
        si.write(co.read())
        self.assertEqual(server.read(), b'offline telemetry test')

    def test_additional_topics_decode_without_guesses_or_private_fields(self):
        sensors={x.key:x for x in b.SENSORS}
        read=lambda key,payload:b.structured_reading(sensors[key],payload)
        self.assertEqual(read('supply_motor_runtime',b'360000')[0],'100')
        self.assertEqual(read('supply_motor_runtime',b'0')[1]['reported_seconds'],0)
        self.assertIsNone(read('supply_motor_runtime',b'-1'))
        self.assertEqual(read('wifi_firmware',b'2003014')[0],'2.3.14')
        self.assertEqual(read('filter_1_type',b'ISO Coarse 65%')[0],'ISO Coarse 65%')
        self.assertEqual(read('filter_1_type',b'')[0],'Not specified')
        self.assertEqual(read('filter_last_change',b'0000-00-00T00:00:00')[0],'Not set')
        name,attrs=read('model_details',b'{"mn":"Synthetic controller","fwv":2011005,"brid":2,"tlsKey":"PRIVATE","ssid":"PRIVATE"}')
        self.assertEqual(attrs['firmware_version'],'2.11.5')
        self.assertNotIn('tlsKey',attrs);self.assertNotIn('ssid',attrs)

    def test_bypass_frost_and_airquality_preserve_unknowns_and_missing_values(self):
        sensors={x.key:x for x in b.SENSORS}
        read=lambda key,payload:b.structured_reading(sensors[key],payload)
        name,attrs=read('bypass_status',b'{"am":1,"pos":2,"op":0}')
        self.assertEqual(name,'Closed');self.assertEqual(attrs['percent_open'],0)
        self.assertEqual(read('bypass_status',b'{"am":250,"pos":250,"op":101}')[0],'Unknown position code 250')
        self.assertNotIn('percent_open',read('bypass_status',b'{"am":1,"pos":2}')[1])
        self.assertIsNone(read('bypass_status',b'{"am":false,"pos":2,"op":0}'))
        self.assertEqual(read('frost_status',b'{"sta":3,"pwr":20,"usa":4}')[0],'Preheater balanced')
        self.assertIsNone(read('frost_status',b'{}'))
        self.assertEqual(read('air_quality',b'0')[0],'Disabled')
        self.assertEqual(read('air_quality',b'200')[0],'Unknown code 200')
        self.assertIsNone(read('air_quality',b'garbage'))

    def test_extra_data_is_bounded_and_has_no_write_or_wildcard_topics(self):
        self.assertEqual(len(b.SENSORS),40)
        self.assertEqual(len({x.suffix for x in b.SENSORS}),40)
        for sensor in b.SENSORS:
            self.assertNotIn('/wr',sensor.suffix)
            self.assertFalse(any(c in sensor.suffix for c in '+#'))
        self.assertIsNone(b.text_reading(b'x'*801))
        self.assertIsNone(b.text_reading(b'{"key":"secret"}'))
        self.assertIsNone(b.text_reading(b'name\x00secret'))


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_qos0_publishing_does_not_cause_false_timeout(self):
        now = [100.0]
        reader, writer = asyncio.StreamReader(), Writer()
        with patch.object(b.time, 'monotonic', side_effect=lambda: now[0]):
            wire = b.Wire(reader, writer, b.BROKER_OUTBOUND)
            wire.last_rx = 0.0  # No reply is expected for prior QoS-0 publications.

            async def tick(_):
                now[0] += 1
                wire.last_tx = now[0]  # Simulate continuous outgoing sensor data.
                if wire.pending_ping is not None:
                    reader.feed_data(b'\xd0\0')
                    await wire.read()
                if now[0] >= 300:
                    raise asyncio.CancelledError()

            with patch.object(b.asyncio, 'sleep', side_effect=tick):
                with self.assertRaises(asyncio.CancelledError):
                    await b.heartbeat(wire)
        self.assertEqual(writer.data, b'\xc0\0' * 4)

    async def test_keepalive_is_advertised_and_heartbeats_leave_margin(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b.connect_packet('test-client', '', ''))
        _, body = await b.read_packet(reader)
        self.assertEqual(struct.unpack_from('!H', body, 8)[0], 60)
        self.assertEqual(b.PING_INTERVAL_SECONDS, 45)
        self.assertLess(b.PING_INTERVAL_SECONDS + 10, b.KEEPALIVE_SECONDS)

    async def test_missing_ping_reply_times_out(self):
        now = [100.0]
        with patch.object(b.time, 'monotonic', side_effect=lambda: now[0]):
            wire = b.Wire(asyncio.StreamReader(), Writer(), b.DEVICE_OUTBOUND)

            async def tick(_):
                now[0] += 1

            with patch.object(b.asyncio, 'sleep', side_effect=tick):
                with self.assertRaises(TimeoutError):
                    await b.heartbeat(wire)
            self.assertEqual(wire.writer.data, b'\xc0\0')

    async def test_fragmented_packet_and_variable_length(self):
        reader = asyncio.StreamReader()
        expected = b.packet(0x30, b'x'*300)

        async def feed():
            for byte in expected:
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(0)

        task = asyncio.create_task(feed())
        self.assertEqual(await b.read_packet(reader), (0x30, b'x'*300))
        await task

    async def test_malformed_or_oversized_frame_is_bounded(self):
        for data in (b'\x30\x80\x80\x80\x80', b'\x30\xff\xff\x7f'):
            r = asyncio.StreamReader()
            r.feed_data(data)
            with self.assertRaises(ValueError):
                await b.read_packet(r)
        r = asyncio.StreamReader()
        r.feed_data(b'\x30\x03x')
        r.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await b.read_packet(r)

    async def test_device_publish_blocked_even_through_local_helper(self):
        w = Writer()
        wire = b.Wire(asyncio.StreamReader(), w, b.DEVICE_OUTBOUND)
        for header in (0x30, 0x31, 0x32, 0x33):
            with self.assertRaises(PermissionError):
                await wire.send(b.packet(header, b'anything'))
        with self.assertRaises(PermissionError):
            await b.publish_local(wire, 'some/topic', 'some value')
        self.assertEqual(w.data, b'')

    async def test_connect_clean_session_without_will(self):
        r = asyncio.StreamReader()
        r.feed_data(b.connect_packet('test-client', '', 'test'))
        header, body = await b.read_packet(r)
        self.assertEqual(header, 0x10)
        self.assertEqual(body[:7], b'\x00\x04MQTT\x04')
        flags = body[7]
        self.assertTrue(flags & 2)
        self.assertEqual(flags & 0x3c, 0)  # No Will Flag/QoS/Retain.
        self.assertEqual(body[8:10], b'\x00\x3c')

    async def test_availability_will_is_only_for_the_home_assistant_broker(self):
        with patch.object(asyncio, 'open_connection') as connect:
            with self.assertRaises(PermissionError):
                await b.open_mqtt('unit', 8883, '', '', 'test', b.DEVICE_OUTBOUND,
                                  will=('ha/availability', 'offline'))
            connect.assert_not_called()
        reader = asyncio.StreamReader()
        reader.feed_data(b.connect_packet('local-test', '', '', ('ha/availability', 'offline')))
        _, body = await b.read_packet(reader)
        self.assertEqual(body[7], 0x26)
        self.assertEqual(body[10:], b.mqtt_string('local-test')+
                         b.mqtt_string('ha/availability')+b.mqtt_string('offline'))

    async def test_alias_to_unit_is_rejected_even_on_other_port(self):
        async def resolve(host, port, **kwargs):
            return [(2, 1, 6, '', ('192.0.2.10', port))]
        with patch.object(asyncio.get_running_loop(), 'getaddrinfo', side_effect=resolve):
            with self.assertRaises(b.ConfigurationError):
                await b.ensure_separate_endpoints(options())

    async def test_device_stream_forwards_only_exact_numeric_topics(self):
        dr, dw, lr, lw = asyncio.StreamReader(), Writer(), asyncio.StreamReader(), Writer()
        device = b.Wire(dr, dw, b.DEVICE_OUTBOUND)
        local = b.Wire(lr, lw, b.BROKER_OUTBOUND)
        s = b.SENSORS[0]
        topic = 'unit/' + s.suffix
        mapping = {topic: s}
        dr.feed_data(b.packet(0x90, b'\0\1\0'))
        dr.feed_data(b.packet(0x32, b.mqtt_string(topic) + b'\0\7' + b'1200'))
        dr.feed_data(b.packet(0x30, b.mqtt_string('unit/vent/cm/wr') + b'99'))
        dr.feed_data(b.packet(0x30, b.mqtt_string(topic) + b'nan'))
        dr.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await b.device_receive(device, local, mapping, 'ha/unit')
        # Device receives only the QoS acknowledgement, never PUBLISH.
        self.assertEqual(dw.data, b'\x40\x02\0\7')
        result = asyncio.StreamReader()
        result.feed_data(lw.data)
        result.feed_eof()
        packets = []
        while not result.at_eof():
            packets.append(b.parse_publish(*(await b.read_packet(result))))
        self.assertEqual(packets[:2], [('ha/unit/availability', b'online', None),
                                      ('ha/unit/supply_rpm', b'1200', None)])
        self.assertEqual(len(packets), 3)
        self.assertEqual(packets[2][0], 'ha/unit/last_reading')

    async def test_ha_resubscription_restores_retained_state_and_replaces_attributes(self):
        # A tiny retained-message broker models a fresh HA subscriber; there is
        # no device connection and no additional device request to obtain replay.
        writer = Writer()
        local = b.Wire(asyncio.StreamReader(), writer, b.BROKER_OUTBOUND)
        sensor = next(s for s in b.SENSORS if s.key == 'model_details')
        await b.publish_reading_local(local, 'ha/unit', sensor, 'Synthetic model', {'model_code':42})
        await b.publish_reading_local(local, 'ha/unit', sensor, 'Synthetic model', {})
        reader = asyncio.StreamReader(); reader.feed_data(writer.data); reader.feed_eof()
        retained = {}
        while not reader.at_eof():
            header, body = await b.read_packet(reader)
            self.assertEqual(header, 0x31)
            topic, value, _ = b.parse_publish(header, body)
            retained[topic] = value
        # New HA subscriptions receive both unchanged state and cleared attrs.
        replay = dict(retained)
        self.assertEqual(replay['ha/unit/model_details'], b'Synthetic model')
        self.assertEqual(json.loads(replay['ha/unit/model_details/attributes']), {})

    async def test_retained_caches_are_cleared_before_each_new_device_session(self):
        writer = Writer(); local = b.Wire(asyncio.StreamReader(), writer, b.BROKER_OUTBOUND)
        await b.clear_local_readings(local, 'ha/unit')
        reader = asyncio.StreamReader(); reader.feed_data(writer.data); reader.feed_eof()
        cleared = set()
        while not reader.at_eof():
            header, body = await b.read_packet(reader)
            self.assertEqual(header, 0x31)
            topic, payload, _ = b.parse_publish(header, body)
            self.assertEqual(payload, b'')
            cleared.add(topic)
        expected = {f'ha/unit/{s.key}' for s in b.SENSORS}
        expected |= {f'ha/unit/{s.key}/attributes' for s in b.SENSORS if s.format != 'number'}
        expected.add('ha/unit/last_reading')
        self.assertEqual(cleared, expected)

    async def test_retained_reading_helper_cannot_publish_to_device(self):
        writer = Writer(); device = b.Wire(asyncio.StreamReader(), writer, b.DEVICE_OUTBOUND)
        with self.assertRaises(PermissionError):
            await b.publish_reading_local(device, 'ha/unit', b.SENSORS[0], '1200', {})
        self.assertEqual(writer.data, b'')

    async def test_rejected_subscription_does_not_mark_online(self):
        dr, dw, lw = asyncio.StreamReader(), Writer(), Writer()
        dr.feed_data(b.packet(0x90, b'\0\1\x80'))
        with self.assertRaises(ValueError):
            await b.device_receive(b.Wire(dr, dw, b.DEVICE_OUTBOUND),
                                   b.Wire(asyncio.StreamReader(), lw, b.BROKER_OUTBOUND),
                                   {'topic': b.SENSORS[0]}, 'ha/unit')
        self.assertEqual(lw.data, b'')

    async def test_one_topic_per_subscription_and_all_acks_required(self):
        mapping = {'unit/vent/afs/rpm': b.SENSORS[0], 'unit/vent/afe/rpm': b.SENSORS[1]}
        packets = list(b.subscription_packets(mapping))
        self.assertEqual(len(packets), 2)
        for identifier, (topic, raw) in enumerate(zip(mapping, packets), 1):
            reader = asyncio.StreamReader()
            reader.feed_data(raw)
            header, body = await b.read_packet(reader)
            self.assertEqual(header, 0x82)
            self.assertEqual(body, struct.pack('!H', identifier) + b.mqtt_string(topic) + b'\0')
        dr, lw = asyncio.StreamReader(), Writer()
        dr.feed_data(b.packet(0x90, b'\0\1\0'))
        dr.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await b.device_receive(b.Wire(dr, Writer(), b.DEVICE_OUTBOUND),
                                   b.Wire(asyncio.StreamReader(), lw, b.BROKER_OUTBOUND), mapping, 'ha/unit')
        self.assertEqual(lw.data, b'')

    async def test_qos2_and_truncated_publish_fail(self):
        for header, body in ((0x34, b'\0\1a\0\1x'), (0x30, b'\0\x10a'),
                             (0x32, b'\0\1a\0\0x')):
            with self.assertRaises(ValueError):
                b.parse_publish(header, body)


if __name__ == '__main__':
    unittest.main()
