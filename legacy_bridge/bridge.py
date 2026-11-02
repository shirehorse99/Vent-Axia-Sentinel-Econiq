"""Experimental Econiq MQTT telemetry bridge. No device PUBLISH packets."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import re
import signal
import socket
import ssl
import struct
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger("ventaxia_readonly")
MAX_PACKET = 65536
KEEPALIVE_SECONDS = 60
PING_INTERVAL_SECONDS = 45
# Explicit protocol allowlist. Type 3 (PUBLISH) cannot leave the device socket.
DEVICE_OUTBOUND = frozenset({1, 4, 8, 12, 14})
BROKER_OUTBOUND = frozenset({1, 3, 12, 14})


@dataclass(frozen=True)
class Sensor:
    key: str
    name: str
    suffix: str
    unit: str | None = None
    device_class: str | None = None
    format: str = "number"


# Only readings confirmed in the app's topic constants AND handlers.
# Airflow units/filter-life units remain unverified and are not assigned here.
SENSORS = (
    Sensor("supply_rpm", "Supply fan speed", "vent/afs/rpm", "rpm"),
    Sensor("extract_rpm", "Extract fan speed", "vent/afe/rpm", "rpm"),
    Sensor("outdoor_temperature", "Outdoor temperature", "io/t1", "°C", "temperature"),
    Sensor("supply_temperature", "Supply temperature", "io/t2", "°C", "temperature"),
    Sensor("indoor_temperature", "Indoor temperature", "io/t3", "°C", "temperature"),
    Sensor("internal_humidity", "Intake humidity", "io/irh/val", "%", "humidity"),
    Sensor("external_humidity", "Extract humidity", "io/erh/val", "%", "humidity"),
    Sensor("system_power", "System power", "mdet/pwr", "W", "power"),
    Sensor("co2", "CO2", "io/ico2/val", "ppm", "carbon_dioxide"),
    Sensor("supply_airflow", "Supply airflow reading", "vent/afs/fd"),
    Sensor("extract_airflow", "Extract airflow reading", "vent/afe/fd"),
    Sensor("supply_measured_airflow", "Supply measured airflow reading", "vent/afs/fm"),
    Sensor("extract_measured_airflow", "Extract measured airflow reading", "vent/afe/fm"),
    Sensor("filter_1_remaining", "Filter 1 life reading", "vent/filter1/lr"),
    Sensor("filter_2_remaining", "Filter 2 life reading", "vent/filter2/lr"),
    Sensor("airflow_preset", "Reported airflow preset", "vent/caf", format="preset"),
    Sensor("faults", "Fault flags", "mdet/faults", format="faults"),
    Sensor("warnings", "Warning flags", "mdet/warns", format="warnings"),
    Sensor("notices", "Notice flags", "mdet/noti", format="notices"),
    Sensor("override", "Reported override cause", "vent/cor", format="override"),
    Sensor("regulation", "Airflow regulation", "vent/cm", format="regulation"),
    Sensor("wifi_signal", "Wi-Fi signal", "mdet/wifi/sta", "dBm", "signal_strength", "wifi"),
    Sensor("bypass_status", "Summer bypass status", "vent/sbs", format="bypass"),
    Sensor("frost_status", "Frost protection status", "vent/afstat", format="frost"),
    Sensor("supply_motor_power", "Supply motor power", "vent/afs/pwr", "W", "power"),
    Sensor("extract_motor_power", "Extract motor power", "vent/afe/pwr", "W", "power"),
    Sensor("supply_motor_runtime", "Supply motor runtime", "vent/afs/dr", "h", "duration", "runtime"),
    Sensor("extract_motor_runtime", "Extract motor runtime", "vent/afe/dr", "h", "duration", "runtime"),
    Sensor("unit_runtime", "Unit runtime", "mdet/runt", "h", "duration", "runtime"),
    Sensor("filter_last_change", "Last filter change reported", "vent/filtertmr/last", format="reported_date"),
    Sensor("filter_interval", "Filter interval reading", "vent/filtertmr/int", format="nonnegative"),
    Sensor("service_last", "Last service reported", "mdet/svctmr/last", format="reported_date"),
    Sensor("service_interval", "Service interval", "mdet/svctmr/int", "months", format="nonnegative"),
    Sensor("filter_1_type", "Filter 1 type", "vent/filter1/typ", format="filter_type"),
    Sensor("filter_2_type", "Filter 2 type", "vent/filter2/typ", format="filter_type"),
    Sensor("model_details", "Model details", "mdet/moddet", format="model"),
    Sensor("wifi_firmware", "Wi-Fi firmware", "mdet/wifi/fwv", format="firmware"),
    Sensor("wifi_hardware", "Wi-Fi hardware identifier", "mdet/wifi/ht", format="text"),
    Sensor("air_quality", "Reported air quality", "vent/saq", format="air_quality"),
    Sensor("unit_name", "Reported unit name", "mdet/name", format="text"),
)

# Exact AirflowPreset enum in the supplied v7 app. Quiet is the user's label;
# its equivalence to the app's Low entry remains to be verified on the unit.
PRESETS = {0: "Off", 1: "Low", 2: "Normal", 3: "Boost", 4: "Purge",
           254: "None", 255: "Maximum"}
OVERRIDES = {0:"None",1:"Zonal schedule",2:"Extract CO2",3:"Extract humidity",4:"Zonal CO2",
             5:"Zonal VOC",6:"Zonal humidity",7:"Summer bypass",8:"Zonal switch",9:"User override",
             10:"Quiet hours",11:"Frost protection modifier",12:"Damper speed limit",
             13:"Filter calibration",14:"Shutdown",15:"Commissioning",16:"Standby",
             17:"Diagnostic mode",18:"Heating failure",19:"Controlled mode",20:"Night cooling",
             21:"NV Smart",22:"Testing",23:"Zonal 0–10 V",24:"System disabled",25:"Thermal override",
             26:"Cooler enabled",27:"AC override",28:"Science override"}
REGULATION = {0:"Fixed percentage",1:"Constant volume",2:"Constant pressure"}


BYPASS_POSITIONS = {0:"Unknown",1:"Closing",2:"Closed",3:"Opening",4:"Open",5:"Modulated"}
BYPASS_MODES = {0:"Inactive",1:"Normal",2:"Evening fresh",3:"Night fresh",4:"Frost protection",5:"Diagnostic open",6:"Service mode",7:"BMS override"}
FROST_MODES = {0:"Inactive",1:"Airflow imbalance",2:"Bypass",3:"Preheater balanced",4:"Preheater imbalanced"}
AIR_QUALITY = {0:"Disabled",1:"Good",2:"Neutral",3:"Bad"}


class ConfigurationError(ValueError):
    pass


class AuthenticationError(Exception):
    pass


def validate_options(o: dict) -> bytes:
    for name in ("device_host", "mqtt_host"):
        value = o.get(name)
        if not isinstance(value, str) or not value or any(c.isspace() for c in value):
            raise ConfigurationError(f"Set {name} to a hostname or IP address.")
    for name in ("device_port", "mqtt_port"):
        value = o.get(name)
        if type(value) is not int or not 1 <= value <= 65535:
            raise ConfigurationError(f"{name} must be a port number.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", o.get("device_id", "")):
        raise ConfigurationError("Set device_id to the unit's Bluetooth device ID.")
    identity = o.get("tls_identity", "")
    if not isinstance(identity, str) or not identity or len(identity.encode()) > 256 or "\0" in identity:
        raise ConfigurationError("Set a valid TLS identity.")
    key_text = o.get("tls_psk_hex", "")
    if not isinstance(key_text, str) or not re.fullmatch(r"(?:[0-9A-Fa-f]{2}){1,256}", key_text):
        raise ConfigurationError("A valid device TLS key in hexadecimal is required. Home Wi-Fi passwords and PINs do not supply this key.")
    key = bytes.fromhex(key_text)
    if not any(key):
        raise ConfigurationError("The current app treats an all-zero key as unavailable. Obtain a valid key before starting.")
    if type(o.get("mqtt_tls")) is not bool:
        raise ConfigurationError("mqtt_tls must be true or false.")
    for name in ("device_username", "device_password", "mqtt_username", "mqtt_password"):
        if not isinstance(o.get(name), str) or "\0" in o[name]:
            raise ConfigurationError(f"{name} must be a string without NUL bytes.")
    if o["device_host"].lower() == o["mqtt_host"].lower():
        raise ConfigurationError("The Home Assistant broker must be separate from the device broker.")
    return key


def device_tls(identity: str, key: bytes) -> ssl.SSLContext:
    if not getattr(ssl, "HAS_PSK", False):
        raise ConfigurationError("This Python/OpenSSL build lacks TLS-PSK support.")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Peer is authenticated by the PSK, not a certificate.
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("PSK-AES128-CBC-SHA")
    ctx.set_psk_client_callback(lambda hint: (identity, key))
    return ctx


def mqtt_string(value: str) -> bytes:
    data = value.encode("utf-8")
    if len(data) > 65535 or b"\0" in data:
        raise ValueError("Invalid MQTT string")
    return struct.pack("!H", len(data)) + data


def packet(header: int, body: bytes = b"") -> bytes:
    size = len(body)
    if size > MAX_PACKET:
        raise ValueError("MQTT packet too large")
    encoded = bytearray([header])
    while True:
        digit, size = size % 128, size // 128
        encoded.append(digit | (128 if size else 0))
        if not size:
            break
    return bytes(encoded) + body


def connect_packet(client_id: str, username: str, password: str, will=None) -> bytes:
    flags = 2  # Clean session. No last will; no write caused by disconnect.
    payload = mqtt_string(client_id)
    if will is not None:
        flags |= 0x24  # Retained QoS-0 will, only on the separate HA broker.
        payload += mqtt_string(will[0]) + mqtt_string(will[1])
    if username or password:
        flags |= 0xC0
        payload += mqtt_string(username) + mqtt_string(password)
    return packet(0x10, mqtt_string("MQTT") + bytes([4, flags]) + struct.pack("!H", KEEPALIVE_SECONDS) + payload)


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = (await reader.readexactly(1))[0]
    length, multiplier = 0, 1
    for index in range(4):
        digit = (await reader.readexactly(1))[0]
        length += (digit & 127) * multiplier
        if length > MAX_PACKET:
            raise ValueError("Oversized MQTT packet")
        if digit < 128:
            return header, await reader.readexactly(length)
        multiplier *= 128
    raise ValueError("Invalid MQTT remaining length")


def parse_publish(header: int, body: bytes) -> tuple[str, bytes, int | None]:
    qos = (header >> 1) & 3
    if header >> 4 != 3 or qos > 1 or len(body) < 2:
        raise ValueError("Unsupported MQTT PUBLISH")
    length = struct.unpack_from("!H", body)[0]
    end = 2 + length
    if not length or end + (2 if qos else 0) > len(body):
        raise ValueError("Truncated MQTT PUBLISH")
    topic = body[2:end].decode("utf-8", errors="strict")
    if any(c in topic for c in ("\0", "+", "#")):
        raise ValueError("Invalid MQTT publication topic")
    identifier = struct.unpack_from("!H", body, end)[0] if qos else None
    if identifier == 0:
        raise ValueError("Invalid MQTT packet identifier")
    return topic, body[end + (2 if qos else 0):], identifier


class Wire:
    def __init__(self, reader, writer, allowed):
        self.reader, self.writer, self.allowed = reader, writer, frozenset(allowed)
        self.last_tx = self.last_rx = time.monotonic()
        self.last_ping = time.monotonic()
        self.pending_ping = None

    async def send(self, data: bytes):
        if data[0] >> 4 not in self.allowed:
            raise PermissionError("Packet type forbidden on this connection")
        self.writer.write(data)
        await asyncio.wait_for(self.writer.drain(), 5)
        self.last_tx = time.monotonic()

    async def read(self):
        result = await read_packet(self.reader)
        self.last_rx = time.monotonic()
        if result == (0xD0, b""):
            self.pending_ping = None
        return result

    async def close(self):
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.send(packet(0xE0)), 2)
        self.writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.writer.wait_closed(), 2)


async def open_mqtt(host, port, username, password, client_id, allowed, tls=None, will=None):
    if will is not None and 3 not in allowed:
        raise PermissionError("No last will is permitted on the device connection")
    kwargs = {"ssl": tls, "ssl_handshake_timeout": 10} if tls else {}
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, **kwargs), 15)
    wire = Wire(reader, writer, allowed)
    try:
        await wire.send(connect_packet(client_id, username, password, will))
        header, body = await asyncio.wait_for(wire.read(), 10)
        if header != 0x20 or len(body) != 2 or body[0] != 0:
            raise ValueError("Invalid MQTT CONNACK")
        if body[1]:
            raise AuthenticationError("MQTT connection rejected; check configured broker credentials.")
        return wire
    except BaseException:
        await wire.close()
        raise


async def publish_local(wire: Wire, topic: str, value: str, *, retained=False):
    await wire.send(packet(0x31 if retained else 0x30, mqtt_string(topic) + value.encode()))



async def publish_reading_local(local: Wire, stem: str, sensor: Sensor, value: str, attributes: dict):
    # Retention is exclusively on HA's broker, never on the device connection.
    # Always send {} when attributes disappear, replacing any retained old keys.
    if sensor.format != "number":
        await publish_local(local, f"{stem}/{sensor.key}/attributes", json.dumps(attributes), retained=True)
    await publish_local(local, f"{stem}/{sensor.key}", value, retained=True)


async def clear_local_readings(local: Wire, stem: str):
    # A new device session must earn fresh readings. Clear broker caches while
    # availability is offline so retained data from an older session isn't live.
    for sensor in SENSORS:
        await publish_local(local, f"{stem}/{sensor.key}", "", retained=True)
        if sensor.format != "number":
            await publish_local(local, f"{stem}/{sensor.key}/attributes", "", retained=True)
    await publish_local(local, stem + "/last_reading", "", retained=True)


def discovery(sensor: Sensor, device_id: str, stem: str) -> dict:
    result = {
        "name": sensor.name,
        "unique_id": f"ventaxia_readonly_{device_id}_{sensor.key}",
        "state_topic": f"{stem}/{sensor.key}",
        "availability_topic": f"{stem}/availability",
        "device": {"identifiers": [f"ventaxia_readonly_{device_id}"],
                   "name": f"Sentinel Econiq {device_id}", "manufacturer": "Vent-Axia"},
    }
    if sensor.format in ("runtime", "model", "firmware", "text", "nonnegative", "filter_type", "frost", "air_quality", "reported_date"):
        result["entity_category"] = "diagnostic"
    if sensor.unit:
        result["unit_of_measurement"] = sensor.unit
        result["state_class"] = "total_increasing" if sensor.format=="runtime" else "measurement"
        if sensor.format=="nonnegative":result.pop("state_class",None)
    if sensor.device_class:
        result["device_class"] = sensor.device_class
    if sensor.format != "number":
        result["json_attributes_topic"] = f"{stem}/{sensor.key}/attributes"
    return result


def diagnostic_discovery(device_id: str, stem: str):
    common = discovery(SENSORS[0], device_id, stem)["device"]
    return (
        ("binary_sensor", "connection", {"name": "Connection", "unique_id": f"ventaxia_readonly_{device_id}_connection",
         "state_topic": stem + "/availability", "payload_on": "online", "payload_off": "offline",
         "device_class": "connectivity", "entity_category": "diagnostic", "device": common}),
        ("sensor", "last_reading", {"name": "Last telemetry received", "unique_id": f"ventaxia_readonly_{device_id}_last_reading",
         "state_topic": stem + "/last_reading", "device_class": "timestamp", "entity_category": "diagnostic",
         "device": common}),
        ("sensor", "reconnects", {"name":"Reconnect attempts this run", "unique_id":f"ventaxia_readonly_{device_id}_reconnects",
         "state_topic":stem+"/reconnects", "entity_category":"diagnostic", "device":common}),
        ("sensor", "bridge_started", {"name":"Bridge started at", "unique_id":f"ventaxia_readonly_{device_id}_bridge_started",
         "state_topic":stem+"/bridge_started", "device_class":"timestamp", "entity_category":"diagnostic", "device":common}),
    )


async def heartbeat(wire: Wire):
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        if wire.pending_ping is not None and now - wire.pending_ping > 10:
            raise TimeoutError("MQTT keepalive reply missing")
        if wire.pending_ping is None and now - wire.last_ping >= PING_INTERVAL_SECONDS:
            wire.pending_ping = now
            wire.last_ping = now
            await wire.send(packet(0xC0))


async def local_receive(wire: Wire):
    while True:
        header, body = await wire.read()
        if header != 0xD0 or body:
            raise ValueError("Unexpected local-broker packet")


def numeric_reading(payload: bytes) -> str | None:
    if len(payload) > 128:
        return None
    try:
        value = float(payload.decode("ascii"))
    except (UnicodeError, ValueError):
        return None
    return format(value, ".12g") if math.isfinite(value) else None


def preset_reading(payload: bytes):
    if len(payload) > 4096:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or type(data.get("ps")) is not int:
        return None
    code = data["ps"]
    if not 0 <= code <= 255:
        return None
    attributes = {"preset_code": code,
                  "interpretation": "Board-reported preset; temporary overrides may be separate."}
    proportion = data.get("prop")
    if type(proportion) in (int, float) and -1e9 <= proportion <= 1e9 and math.isfinite(proportion):
        attributes["reported_proportion"] = proportion
    return PRESETS.get(code, f"Unknown code {code}"), attributes


def integer_payload(payload: bytes):
    if len(payload) > 32:
        return None
    try:
        text = payload.decode("ascii").strip()
        if re.fullmatch(r"-?[0-9]+", text):
            # The current app's integer schema uses decimal MQTT payloads.
            return int(text, 10)
        if re.fullmatch(r"(?:0[xX]|#)[0-9a-fA-F]+", text):
            return int(text[1:] if text.startswith('#') else text[2:], 16)
    except (ValueError, UnicodeError):
        pass
    return None


def status_reading(kind: str, payload: bytes):
    value = integer_payload(payload)
    if value is None or not -(1 << 31) <= value < (1 << 32):
        return None
    mask = value & 0xffffffff
    prefix, known_bits = {"faults":("F", set(range(8)) | {31}),
                          "warnings":("W", set(range(21))), "notices":("N", set(range(5)))}[kind]
    bits = [bit for bit in range(32) if mask & (1 << bit)]
    unknown = sum(1 << bit for bit in bits if bit not in known_bits)
    return str(mask.bit_count()), {"raw_mask":mask, "raw_hex":f"0x{mask:08X}",
            "codes":[f"{prefix}{bit+1:02}" for bit in bits if bit in known_bits],
            "unknown_bits_hex":f"0x{unknown:08X}", "status":"Reported" if mask else "Clear"}



def text_reading(payload: bytes):
    if len(payload) > 800:
        return None
    try:
        value = payload.decode("utf-8", errors="strict").strip()
    except UnicodeError:
        return None
    if not value or len(value) > 200 or not value.isprintable() or value.startswith(("{", "[")):
        return None
    return value


def firmware_reading(payload: bytes):
    value = text_reading(payload)
    if value is None:return None
    if re.fullmatch(r"[0-9]{1,12}", value):
        packed=int(value)
        return f"{packed//1000000}.{(packed//1000)%1000}.{packed%1000}", {"reported_version":value}
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}",value):
        return value, {"reported_version":value}
    return None


def additional_reading(sensor: Sensor, payload: bytes):
    kind = sensor.format
    if kind == "text":
        value = text_reading(payload)
        return (value, {}) if value is not None else None
    if kind == "reported_date":
        if not payload.strip():return "Not set", {}
        value=text_reading(payload)
        if value is None:return None
        if re.fullmatch(r"0000-00-00(?:T00:00:00(?:\.0+)?Z?)?",value):return "Not set", {"reported_date":value}
        return value, {"reported_date":value,"interpretation":"Device-reported date; unit clock/timezone not independently verified."}
    if kind == "firmware":
        return firmware_reading(payload)
    if kind == "filter_type":
        if not payload.strip():return "Not specified", {"reported_filter_type":""}
        value=text_reading(payload)
        return (value, {"reported_filter_type":value}) if value is not None else None
    if kind in ("runtime", "nonnegative", "air_quality"):
        value = integer_payload(payload)
        if value is None or not 0 <= value <= (1 << 53)-1:
            return None
        if kind == "runtime":
            return format(value/3600,".12g"), {"reported_seconds":value}
        if kind == "nonnegative":
            return str(value), {"interpretation":"Device-reported service interval in months." if sensor.key=="service_interval" else "Device-reported filter interval; unit not yet confirmed."}
        if kind == "air_quality":
            return AIR_QUALITY.get(value, f"Unknown code {value}"), {"air_quality_code":value}
    if kind not in ("bypass", "frost", "model") or len(payload)>4096:
        return None
    try:
        data=json.loads(payload)
    except (ValueError,UnicodeError):
        return None
    if not isinstance(data,dict):
        return None
    if kind == "bypass":
        pos,mode=data.get("pos"),data.get("am")
        if type(pos) is not int or type(mode) is not int or not 0<=pos<=255 or not 0<=mode<=255:
            return None
        attrs={"position_code":pos,"operating_mode_code":mode,"operating_mode":BYPASS_MODES.get(mode,f"Unknown code {mode}")}
        opening=data.get("op")
        if type(opening) in (int,float) and math.isfinite(opening):
            if 0<=opening<=100:attrs["percent_open"]=opening
            else:attrs["opening_raw"]=opening
        return BYPASS_POSITIONS.get(pos,f"Unknown position code {pos}"),attrs
    if kind == "frost":
        mode=data.get("sta")
        if type(mode) is not int or not 0<=mode<=255:return None
        attrs={"mode_code":mode}
        for key,name in (("pwr","power_raw"),("usa","usage_raw")):
            value=data.get(key)
            if type(value) in (int,float) and math.isfinite(value):attrs[name]=value
        attrs["interpretation"]="Reported frost mode; raw power/usage units unverified."
        return FROST_MODES.get(mode,f"Unknown code {mode}"),attrs
    # Whitelist metadata: never forward arbitrary fields or credential-shaped payloads.
    name=data.get("mn")
    if not isinstance(name,str) or not name or len(name)>200 or not name.isprintable():return None
    attrs={}
    for key,label in (("sn","serial_number"),("mc","model_code"),("brid","board_revision_id"),("dom","manufacture_date_reported"),("fwv","firmware_reported")):
        value=data.get(key)
        if type(value) is int or (isinstance(value,str) and len(value)<=128 and value.isprintable()):attrs[label]=value
    if type(data.get("fwv")) is int:
        version=firmware_reading(str(data["fwv"]).encode())
        if version:attrs["firmware_version"]=version[0]
    return name,attrs


def structured_reading(sensor: Sensor, payload: bytes):
    if sensor.format in ("text", "firmware", "runtime", "nonnegative", "air_quality", "filter_type", "bypass", "frost", "model", "reported_date"):
        return additional_reading(sensor, payload)
    if sensor.format == "preset":
        return preset_reading(payload)
    if sensor.format in ("faults", "warnings", "notices"):
        return status_reading(sensor.format, payload)
    if sensor.format == "regulation":
        code = integer_payload(payload)
        if code is None or not 0 <= code <= 255:
            return None
        return REGULATION.get(code, f"Unknown code {code}"), {"regulation_code":code}
    if len(payload) > 4096:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    if sensor.format == "wifi":
        rssi = data.get("rssi")
        if type(rssi) not in (int,float) or not -127 <= rssi <= 0:
            return None
        return format(rssi,".12g"), {}
    if sensor.format == "override":
        code = data.get("ot")
        if type(code) is not int or not 0 <= code <= 255:
            return None
        attributes = {"override_type_code":code}
        if type(data.get("os")) is int:
            attributes["reported_source_id"] = data["os"]
        duration = data.get("treq")
        if isinstance(duration, str) and re.fullmatch(r"[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]", duration):
            hours, minutes, seconds = map(int, duration.split(':'))
            attributes["requested_duration"] = duration
            attributes["requested_seconds"] = hours*3600 + minutes*60 + seconds
        started = data.get("trem")
        if isinstance(started, str) and len(started) <= 64:
            attributes["reported_started_at"] = started
        attributes["interpretation"] = "Reported cause and start time; source ID is not a preset code."
        return OVERRIDES.get(code, f"Unknown code {code}"), attributes
    return None


async def device_receive(device: Wire, local: Wire, mapping: dict, stem: str):
    subscribed = False
    pending = set(range(1, len(mapping) + 1))
    subscription_deadline = time.monotonic() + 15
    last_timestamp = float("-inf")
    while True:
        if not subscribed:
            remaining = subscription_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Device subscription not acknowledged")
            header, body = await asyncio.wait_for(device.read(), remaining)
        else:
            header, body = await device.read()
        if header == 0x90:
            if len(body) != 3 or body[2] != 0:
                raise ValueError("Device did not grant the requested QoS-0 telemetry subscriptions")
            identifier = int.from_bytes(body[:2], "big")
            if identifier not in pending:
                raise ValueError("Unexpected subscription acknowledgement")
            pending.remove(identifier)
            if not pending:
                subscribed = True
                await publish_local(local, f"{stem}/availability", "online", retained=True)
        elif header == 0xD0 and not body:
            continue
        elif header >> 4 == 3:
            topic, payload, identifier = parse_publish(header, body)
            if identifier is not None:
                await device.send(packet(0x40, struct.pack("!H", identifier)))
            sensor = mapping.get(topic)
            if not sensor:
                continue
            if sensor.format != "number":
                reading = structured_reading(sensor, payload)
                if reading is None:
                    continue
                value, attributes = reading
            else:
                value = numeric_reading(payload)
                if value is None:
                    continue
                attributes = {}
            await publish_reading_local(local, stem, sensor, value, attributes)
            if time.monotonic() - last_timestamp >= 30:
                await publish_local(local, stem + "/last_reading", datetime.now(timezone.utc).isoformat(), retained=True)
                last_timestamp = time.monotonic()
        else:
            raise ValueError("Unexpected device MQTT packet")


async def ensure_separate_endpoints(o: dict):
    loop = asyncio.get_running_loop()
    device, broker = await asyncio.gather(
        loop.getaddrinfo(o["device_host"], o["device_port"], type=socket.SOCK_STREAM),
        loop.getaddrinfo(o["mqtt_host"], o["mqtt_port"], type=socket.SOCK_STREAM))
    if {x[4][0] for x in device} & {x[4][0] for x in broker}:
        raise ConfigurationError("The Home Assistant broker resolves to the device endpoint; refusing to publish.")


def subscription_packets(mapping: dict):
    # This board acknowledges a single-topic request correctly. Match the app's
    # one-topic-per-SUBSCRIBE behavior rather than combining topic filters.
    for identifier, topic in enumerate(mapping, 1):
        yield packet(0x82, struct.pack("!H", identifier) + mqtt_string(topic) + b"\0")


async def session(o: dict, key: bytes, reconnects=0, started_at=None):
    await ensure_separate_endpoints(o)
    local = device = None
    tasks = []
    stem = f"ventaxia_readonly/{o['device_id']}"
    nonce = uuid.uuid4().hex[:12]
    try:
        local = await open_mqtt(o["mqtt_host"], o["mqtt_port"], o["mqtt_username"], o["mqtt_password"],
                                "va-ha-" + nonce, BROKER_OUTBOUND,
                                ssl.create_default_context() if o["mqtt_tls"] else None,
                                will=(stem + "/availability", "offline"))
        await publish_local(local, stem + "/availability", "offline", retained=True)
        await clear_local_readings(local, stem)
        for sensor in SENSORS:
            await publish_local(local, f"homeassistant/sensor/ventaxia_{o['device_id']}/{sensor.key}/config",
                                json.dumps(discovery(sensor, o["device_id"], stem)), retained=True)
        for component, key_name, data in diagnostic_discovery(o["device_id"], stem):
            await publish_local(local, f"homeassistant/{component}/ventaxia_{o['device_id']}/{key_name}/config",
                                json.dumps(data), retained=True)
        await publish_local(local, stem+"/reconnects", str(reconnects), retained=True)
        await publish_local(local, stem+"/bridge_started", started_at or datetime.now(timezone.utc).isoformat(), retained=True)
        device = await open_mqtt(o["device_host"], o["device_port"], o["device_username"], o["device_password"],
                                 "va-read-" + nonce, DEVICE_OUTBOUND, device_tls(o["tls_identity"], key))
        mapping = {o["device_id"] + "/" + s.suffix: s for s in SENSORS}
        for data in subscription_packets(mapping):
            await device.send(data)
        LOG.info("Authenticated; requesting %d telemetry subscriptions", len(mapping))
        tasks = [asyncio.create_task(device_receive(device, local, mapping, stem)),
                 asyncio.create_task(local_receive(local)), asyncio.create_task(heartbeat(device)),
                 asyncio.create_task(heartbeat(local))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if local:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(publish_local(local, stem + "/availability", "offline", retained=True), 2)
        for wire in (device, local):
            if wire:
                await wire.close()


async def run(o: dict, key: bytes):
    # Stop on authentication/TLS errors, rather than repeatedly trying credentials.
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    reconnects = 0
    started_at = datetime.now(timezone.utc).isoformat()
    while True:
        try:
            await session(o, key, reconnects, started_at)
        except (ssl.SSLError, AuthenticationError):
            LOG.error("Authentication/TLS failed. Stopped; verify the device key, identity, port and broker credentials.")
            return 2
        except ConfigurationError:
            raise
        except (OSError, TimeoutError, asyncio.IncompleteReadError, ValueError) as error:
            reconnects += 1
            LOG.warning("Connection interrupted (%s). Retrying in 30 seconds; no credential guessing or control requests.", type(error).__name__)
            await asyncio.sleep(30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--options", default="/data/options.json")
    parser.add_argument("--validate", action="store_true", help="Validate configuration without any network requests")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        options = json.loads(Path(args.options).read_text())
        key = validate_options(options)
        device_tls(options["tls_identity"], key)
        if args.validate:
            LOG.info("Configuration valid; no network connection made.")
            return 0
        return asyncio.run(run(options, key))
    except (ConfigurationError, FileNotFoundError, json.JSONDecodeError) as error:
        LOG.error("%s", error)
        return 2
    except KeyboardInterrupt:
        return 0
    except asyncio.CancelledError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
