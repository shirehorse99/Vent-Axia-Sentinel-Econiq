"""Real Home Assistant fixtures; all device connection work is replaced locally.

CI only: python -m pip install -r tests/ha/requirements.txt
python -m pytest -o asyncio_mode=auto tests/ha
Do not add __init__.py here: stdlib unittest discovery should skip this directory.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Support namespace-package custom_components without adding a runtime init file.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
DOMAIN = 'ventaxia_econiq_readonly'


@pytest.fixture(autouse=True)
def custom_integrations_enabled(enable_custom_integrations):
    """Allow the real custom integration loader."""
    yield


@pytest.fixture
def entry_data():
    return {'host':'synthetic-unit.invalid', 'port':8883, 'device_id':'SYNTHETIC-ONE',
            'tls_identity':'synthetic identity', 'tls_psk_hex':'1234567890abcdef',
            'username':'', 'password':''}


@pytest.fixture
def config_entry(hass, entry_data):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=entry_data['device_id'],
                            title='Synthetic unit', data=entry_data)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def isolated_device_worker(monkeypatch):
    """Exercise lifecycle cancellation without any connection, TLS or MQTT IO."""
    from custom_components.ventaxia_econiq_readonly import coordinator
    started, stopped = [], []

    async def local_wait(self):
        started.append(self)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(self)

    monkeypatch.setattr(coordinator.EconiqCoordinator, '_run', local_wait)
    trap = AsyncMock(side_effect=AssertionError('No network is permitted in HA smoke tests'))
    monkeypatch.setattr(coordinator, 'open_mqtt', trap)
    yield {'started':started, 'stopped':stopped, 'network':trap}
    trap.assert_not_awaited()
