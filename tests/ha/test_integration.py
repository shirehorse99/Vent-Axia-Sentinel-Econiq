"""CI smoke tests using actual HA platform/config-entry/entity infrastructure.

Synthetic fixture readings only. No unit access and no configuration commands.
This folder is run explicitly with pytest, not stdlib unittest discovery.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = 'ventaxia_econiq_readonly'
pytestmark = pytest.mark.asyncio


def entity_id(hass, device_id, key, platform='sensor'):
    value = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f'{device_id}_{key}')
    assert value is not None, f'Missing entity {key}'
    return value


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_native_platforms_reported_values_and_unload(hass, config_entry, isolated_device_worker):
    hub = await setup(hass, config_entry)
    task = hub._task
    assert task is not None and not task.done()
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    assert {entry.domain for entry in entries} == {'sensor','binary_sensor'}
    identity = config_entry.data['device_id']
    temperature_id = entity_id(hass, identity, 'supply_temperature')
    assert hass.states.get(temperature_id).state == 'unavailable'
    hub.connected = True
    hub.values.update(supply_temperature=15.5, model_details='Synthetic model')
    hub.attributes['model_details'] = {'model_code':42, 'firmware_version':'1.2.3'}
    hub._notify()
    await hass.async_block_till_done()
    assert float(hass.states.get(temperature_id).state) == 15.5
    model = hass.states.get(entity_id(hass, identity, 'model_details'))
    assert model.attributes['model_code'] == 42
    assert model.attributes['firmware_version'] == '1.2.3'
    assert hass.states.get(entity_id(hass, identity, 'connection','binary_sensor')).state == 'on'
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert task.done()
    assert hub._task is None
    assert hub in isolated_device_worker['stopped']
    state = hass.states.get(temperature_id)
    assert state is None or state.state == 'unavailable'


async def test_real_config_flow_rejects_zero_key_and_requires_ack(hass, entry_data):
    # Capability is patched because the form is tested independently of the CI
    # OpenSSL feature build; no SSL context or connection is constructed.
    with patch('custom_components.ventaxia_econiq_readonly.config_flow.ssl.HAS_PSK', True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={'source':config_entries.SOURCE_USER})
        assert result['type'] == FlowResultType.FORM
        zero = entry_data | {'tls_psk_hex':'0000000000000000','other_clients_stopped':True}
        result = await hass.config_entries.flow.async_configure(result['flow_id'], zero)
        assert result['errors']['base'] == 'invalid_credentials'
        result = await hass.config_entries.flow.async_configure(result['flow_id'], entry_data | {'other_clients_stopped':False})
        assert result['errors']['base'] == 'other_clients_running'
        # Keep this config-flow test offline through creation as well.
        with patch.object(hass.config_entries, 'async_setup', return_value=True):
            result = await hass.config_entries.flow.async_configure(result['flow_id'], entry_data | {'other_clients_stopped':True})
            await hass.async_block_till_done()
        assert result['type'] == FlowResultType.CREATE_ENTRY
        assert result['data']['tls_identity'] == entry_data['tls_identity']
        assert 'other_clients_stopped' not in result['data']


async def test_per_device_recovery_and_store_roundtrip(hass, config_entry, entry_data, freezer):
    freezer.move_to("2026-10-31T12:00:00+00:00")
    first = await setup(hass, config_entry)
    second_entry = MockConfigEntry(domain=DOMAIN, unique_id='SYNTHETIC-TWO',
                                  data=entry_data | {'device_id':'SYNTHETIC-TWO'})
    second_entry.add_to_hass(hass)
    second = await setup(hass, second_entry)
    assert first.recovery is not second.recovery
    freezer.tick(timedelta(minutes=2))
    first.connected = True
    first.values.update(outdoor_temperature=0, supply_temperature=15,
                        indoor_temperature=20, supply_rpm=1000, extract_rpm=900)
    now = datetime.now(timezone.utc)
    first._sample_recovery(now)
    await hass.async_block_till_done()
    ratio_id = entity_id(hass, config_entry.data['device_id'], 'recovery_ratio')
    assert float(hass.states.get(ratio_id).state) == 75
    second_ratio = hass.states.get(entity_id(hass, 'SYNTHETIC-TWO','recovery_ratio'))
    assert second_ratio.state in ('unknown','unavailable')
    saved = first.recovery.snapshot()
    worker = first._task
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert worker.done()
    store = Store(hass, 1, f'{DOMAIN}.{config_entry.entry_id}.statistics')
    data = await store.async_load()
    assert data == saved
    # Reload creates a new per-entry buffer and restores local samples, while
    # current readings remain unavailable until this new session receives them.
    restored = await setup(hass, config_entry)
    assert restored is not first
    assert restored.recovery.stats(now + timedelta(seconds=1))['recovery_samples_24h'] >= 1
    assert not restored.connected
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert await hass.config_entries.async_unload(second_entry.entry_id)
    await hass.async_block_till_done()
