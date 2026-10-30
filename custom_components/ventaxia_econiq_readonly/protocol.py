"""Telemetry-only MQTT framing and parsing; no device publishing API."""
from __future__ import annotations
import asyncio
import contextlib
import json
import math
import re
import ssl
import struct
import time
from dataclasses import dataclass
MAX_PACKET = 65536
KEEPALIVE_SECONDS = 60
PING_INTERVAL_SECONDS = 45
DEVICE_OUTBOUND = frozenset({1, 4, 8, 12, 14})

@dataclass(frozen=True)
class Sensor:
    key: str
    name: str
    suffix: str
    unit: str | None = None
    device_class: str | None = None
    format: str = 'number'
SENSORS = (Sensor('supply_rpm', 'Supply fan speed', 'vent/afs/rpm', 'rpm'), Sensor('extract_rpm', 'Extract fan speed', 'vent/afe/rpm', 'rpm'), Sensor('outdoor_temperature', 'Outdoor temperature', 'io/t1', '°C', 'temperature'), Sensor('supply_temperature', 'Supply temperature', 'io/t2', '°C', 'temperature'), Sensor('indoor_temperature', 'Indoor temperature', 'io/t3', '°C', 'temperature'), Sensor('internal_humidity', 'Intake humidity', 'io/irh/val', '%', 'humidity'), Sensor('external_humidity', 'Extract humidity', 'io/erh/val', '%', 'humidity'), Sensor('system_power', 'System power', 'mdet/pwr', 'W', 'power'), Sensor('co2', 'CO2', 'io/ico2/val', 'ppm', 'carbon_dioxide'), Sensor('supply_airflow', 'Supply airflow reading', 'vent/afs/fd'), Sensor('extract_airflow', 'Extract airflow reading', 'vent/afe/fd'), Sensor('supply_measured_airflow', 'Supply measured airflow reading', 'vent/afs/fm'), Sensor('extract_measured_airflow', 'Extract measured airflow reading', 'vent/afe/fm'), Sensor('filter_1_remaining', 'Filter 1 life reading', 'vent/filter1/lr'), Sensor('filter_2_remaining', 'Filter 2 life reading', 'vent/filter2/lr'), Sensor('airflow_preset', 'Reported airflow preset', 'vent/caf', format='preset'), Sensor('faults', 'Fault flags', 'mdet/faults', format='faults'), Sensor('warnings', 'Warning flags', 'mdet/warns', format='warnings'), Sensor('notices', 'Notice flags', 'mdet/noti', format='notices'), Sensor('override', 'Reported override cause', 'vent/cor', format='override'), Sensor('regulation', 'Airflow regulation', 'vent/cm', format='regulation'), Sensor('wifi_signal', 'Wi-Fi signal', 'mdet/wifi/sta', 'dBm', 'signal_strength', 'wifi'))
PRESETS = {0: 'Off', 1: 'Low', 2: 'Normal', 3: 'Boost', 4: 'Purge', 254: 'None', 255: 'Maximum'}
OVERRIDES = {0: 'None', 1: 'Zonal schedule', 2: 'Extract CO2', 3: 'Extract humidity', 4: 'Zonal CO2', 5: 'Zonal VOC', 6: 'Zonal humidity', 7: 'Summer bypass', 8: 'Zonal switch', 9: 'User override', 10: 'Quiet hours', 11: 'Frost protection modifier', 12: 'Damper speed limit', 13: 'Filter calibration', 14: 'Shutdown', 15: 'Commissioning', 16: 'Standby', 17: 'Diagnostic mode', 18: 'Heating failure', 19: 'Controlled mode', 20: 'Night cooling', 21: 'NV Smart', 22: 'Testing', 23: 'Zonal 0–10 V', 24: 'System disabled', 25: 'Thermal override', 26: 'Cooler enabled', 27: 'AC override', 28: 'Science override'}
REGULATION = {0: 'Fixed percentage', 1: 'Constant volume', 2: 'Constant pressure'}

class ConfigurationError(ValueError):
    pass

class AuthenticationError(Exception):
    pass

def device_tls(identity: str, key: bytes) -> ssl.SSLContext:
    if not getattr(ssl, 'HAS_PSK', False):
        raise ConfigurationError('This Python/OpenSSL build lacks TLS-PSK support.')
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers('PSK-AES128-CBC-SHA')
    ctx.set_psk_client_callback(lambda hint: (identity, key))
    return ctx

def mqtt_string(value: str) -> bytes:
    data = value.encode('utf-8')
    if len(data) > 65535 or b'\x00' in data:
        raise ValueError('Invalid MQTT string')
    return struct.pack('!H', len(data)) + data

def packet(header: int, body: bytes=b'') -> bytes:
    size = len(body)
    if size > MAX_PACKET:
        raise ValueError('MQTT packet too large')
    encoded = bytearray([header])
    while True:
        digit, size = (size % 128, size // 128)
        encoded.append(digit | (128 if size else 0))
        if not size:
            break
    return bytes(encoded) + body

def connect_packet(client_id: str, username: str, password: str) -> bytes:
    flags = 2
    payload = mqtt_string(client_id)
    if username or password:
        flags |= 192
        payload += mqtt_string(username) + mqtt_string(password)
    return packet(16, mqtt_string('MQTT') + bytes([4, flags]) + struct.pack('!H', KEEPALIVE_SECONDS) + payload)

async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = (await reader.readexactly(1))[0]
    length, multiplier = (0, 1)
    for index in range(4):
        digit = (await reader.readexactly(1))[0]
        length += (digit & 127) * multiplier
        if length > MAX_PACKET:
            raise ValueError('Oversized MQTT packet')
        if digit < 128:
            return (header, await reader.readexactly(length))
        multiplier *= 128
    raise ValueError('Invalid MQTT remaining length')

def parse_publish(header: int, body: bytes) -> tuple[str, bytes, int | None]:
    qos = header >> 1 & 3
    if header >> 4 != 3 or qos > 1 or len(body) < 2:
        raise ValueError('Unsupported MQTT PUBLISH')
    length = struct.unpack_from('!H', body)[0]
    end = 2 + length
    if not length or end + (2 if qos else 0) > len(body):
        raise ValueError('Truncated MQTT PUBLISH')
    topic = body[2:end].decode('utf-8', errors='strict')
    if any((c in topic for c in ('\x00', '+', '#'))):
        raise ValueError('Invalid MQTT publication topic')
    identifier = struct.unpack_from('!H', body, end)[0] if qos else None
    if identifier == 0:
        raise ValueError('Invalid MQTT packet identifier')
    return (topic, body[end + (2 if qos else 0):], identifier)

class Wire:

    def __init__(self, reader, writer, allowed):
        self.reader, self.writer, self.allowed = (reader, writer, frozenset(allowed))
        self.last_tx = self.last_rx = time.monotonic()
        self.last_ping = time.monotonic()
        self.pending_ping = None
        self.sent_bytes = 0
        self.received_bytes = 0

    async def send(self, data: bytes):
        if data[0] >> 4 not in self.allowed:
            raise PermissionError('Packet type forbidden on this connection')
        self.writer.write(data)
        await asyncio.wait_for(self.writer.drain(), 5)
        self.last_tx = time.monotonic()
        self.sent_bytes += len(data)

    async def read(self):
        result = await read_packet(self.reader)
        self.last_rx = time.monotonic()
        self.received_bytes += len(packet(*result))
        if result == (208, b''):
            self.pending_ping = None
        return result

    async def close(self):
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.send(packet(224)), 2)
        self.writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.writer.wait_closed(), 2)

async def open_mqtt(host, port, username, password, client_id, allowed, tls=None, will=None):
    if will is not None:
        raise PermissionError('No last will is permitted on the device connection')
    kwargs = {'ssl': tls, 'ssl_handshake_timeout': 10} if tls else {}
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, **kwargs), 15)
    wire = Wire(reader, writer, allowed)
    try:
        await wire.send(connect_packet(client_id, username, password))
        header, body = await asyncio.wait_for(wire.read(), 10)
        if header != 32 or len(body) != 2 or body[0] != 0:
            raise ValueError('Invalid MQTT CONNACK')
        if body[1]:
            raise AuthenticationError('MQTT connection rejected; check configured broker credentials.')
        return wire
    except BaseException:
        await wire.close()
        raise

async def heartbeat(wire: Wire):
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        if wire.pending_ping is not None and now - wire.pending_ping > 10:
            raise TimeoutError('MQTT keepalive reply missing')
        if wire.pending_ping is None and now - wire.last_ping >= PING_INTERVAL_SECONDS:
            wire.pending_ping = now
            wire.last_ping = now
            await wire.send(packet(192))

def numeric_reading(payload: bytes) -> str | None:
    if len(payload) > 128:
        return None
    try:
        value = float(payload.decode('ascii'))
    except (UnicodeError, ValueError):
        return None
    return format(value, '.12g') if math.isfinite(value) else None

def preset_reading(payload: bytes):
    if len(payload) > 4096:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or type(data.get('ps')) is not int:
        return None
    code = data['ps']
    if not 0 <= code <= 255:
        return None
    attributes = {'preset_code': code, 'interpretation': 'Board-reported preset; temporary overrides may be separate.'}
    proportion = data.get('prop')
    if type(proportion) in (int, float) and -1000000000.0 <= proportion <= 1000000000.0 and math.isfinite(proportion):
        attributes['reported_proportion'] = proportion
    return (PRESETS.get(code, f'Unknown code {code}'), attributes)

def integer_payload(payload: bytes):
    if len(payload) > 32:
        return None
    try:
        text = payload.decode('ascii').strip()
        if re.fullmatch('-?[0-9]+', text):
            return int(text, 10)
        if re.fullmatch('(?:0[xX]|#)[0-9a-fA-F]+', text):
            return int(text[1:] if text.startswith('#') else text[2:], 16)
    except (ValueError, UnicodeError):
        pass
    return None

def status_reading(kind: str, payload: bytes):
    value = integer_payload(payload)
    if value is None or not -(1 << 31) <= value < 1 << 32:
        return None
    mask = value & 4294967295
    prefix, known_bits = {'faults': ('F', set(range(8)) | {31}), 'warnings': ('W', set(range(21))), 'notices': ('N', set(range(5)))}[kind]
    bits = [bit for bit in range(32) if mask & 1 << bit]
    unknown = sum((1 << bit for bit in bits if bit not in known_bits))
    return (str(mask.bit_count()), {'raw_mask': mask, 'raw_hex': f'0x{mask:08X}', 'codes': [f'{prefix}{bit + 1:02}' for bit in bits if bit in known_bits], 'unknown_bits_hex': f'0x{unknown:08X}', 'status': 'Reported' if mask else 'Clear'})

def structured_reading(sensor: Sensor, payload: bytes):
    if sensor.format == 'preset':
        return preset_reading(payload)
    if sensor.format in ('faults', 'warnings', 'notices'):
        return status_reading(sensor.format, payload)
    if sensor.format == 'regulation':
        code = integer_payload(payload)
        if code is None or not 0 <= code <= 255:
            return None
        return (REGULATION.get(code, f'Unknown code {code}'), {'regulation_code': code})
    if len(payload) > 4096:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    if sensor.format == 'wifi':
        rssi = data.get('rssi')
        if type(rssi) not in (int, float) or not -127 <= rssi <= 0:
            return None
        return (format(rssi, '.12g'), {})
    if sensor.format == 'override':
        code = data.get('ot')
        if type(code) is not int or not 0 <= code <= 255:
            return None
        attributes = {'override_type_code': code}
        if type(data.get('os')) is int:
            attributes['reported_source_id'] = data['os']
        duration = data.get('treq')
        if isinstance(duration, str) and re.fullmatch('[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]', duration):
            hours, minutes, seconds = map(int, duration.split(':'))
            attributes['requested_duration'] = duration
            attributes['requested_seconds'] = hours * 3600 + minutes * 60 + seconds
        started = data.get('trem')
        if isinstance(started, str) and len(started) <= 64:
            attributes['reported_started_at'] = started
        attributes['interpretation'] = 'Reported cause and start time; source ID is not a preset code.'
        return (OVERRIDES.get(code, f'Unknown code {code}'), attributes)
    return None

def subscription_packets(mapping: dict):
    for identifier, topic in enumerate(mapping, 1):
        yield packet(130, struct.pack('!H', identifier) + mqtt_string(topic) + b'\x00')
