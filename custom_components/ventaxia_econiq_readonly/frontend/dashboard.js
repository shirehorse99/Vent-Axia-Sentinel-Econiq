/* Registry-generated, read-only dashboard. No device calls or service actions. */
(() => {
  const DOMAIN = 'ventaxia_econiq_readonly';
  const ROLLING = ['recovery_mean_1h','recovery_mean_24h','recovery_median_24h',
    'recovery_minimum_24h','recovery_maximum_24h','recovery_sd_24h',
    'recovery_p10_24h','recovery_p90_24h','recovery_samples_24h',
    'recovery_coverage_1h','recovery_coverage_24h','recovery_oldest_sample',
    'recovery_newest_sample','lift_mean_24h','lift_minimum_24h','lift_maximum_24h'];
  const KEYS = new Set(['supply_rpm','extract_rpm','outdoor_temperature','supply_temperature',
    'indoor_temperature','internal_humidity','external_humidity','system_power','co2',
    'supply_airflow','extract_airflow','supply_measured_airflow','extract_measured_airflow',
    'filter_1_remaining','filter_2_remaining','airflow_preset','faults','warnings','notices',
    'override','regulation','wifi_signal','bypass_status','frost_status','supply_motor_power',
    'extract_motor_power','supply_motor_runtime','extract_motor_runtime','unit_runtime',
    'filter_last_change','filter_interval','service_last','service_interval','filter_1_type',
    'filter_2_type','model_details','wifi_firmware','wifi_hardware','air_quality','unit_name',
    'connection','last_telemetry','last_reading','started_at','bridge_started','reconnects',
    'received_messages','received_mqtt_bytes','sent_mqtt_bytes','ping_replies',
    'recovery_ratio','temperature_lift','available_temperature_difference',
    'remaining_temperature_difference','recovery_status', ...ROLLING]);
  const ALIASES = {
    recovery_ratio:'sensor.mvhr_apparent_temperature_recovery',
    temperature_lift:'sensor.mvhr_supply_temperature_lift',
    available_temperature_difference:'sensor.mvhr_available_temperature_difference',
    remaining_temperature_difference:'sensor.mvhr_remaining_temperature_difference',
    recovery_status:'sensor.mvhr_recovery_calculation_status',
    energy_today:'sensor.mvhr_energy_today', energy_month:'sensor.mvhr_energy_this_month',
    ...Object.fromEntries(ROLLING.map(key => [key, `sensor.mvhr_${key}`])),
    recovery_oldest_sample:'sensor.mvhr_recovery_oldest_sample_24h',
  };
  const LABELS = {co2:'CO₂', supply_rpm:'Supply fan speed', extract_rpm:'Extract fan speed', wifi_signal:'Wi-Fi signal', internal_humidity:'Intake humidity', external_humidity:'Extract humidity',
    recovery_ratio:'Apparent temperature recovery', temperature_lift:'Supply temperature lift',
    supply_airflow:'Supply demand (raw)',
    extract_airflow:'Extract demand (raw)',
    supply_measured_airflow:'Supply measured (raw)',
    extract_measured_airflow:'Extract measured (raw)',
    supply_motor_power:'Supply motor power',
    extract_motor_power:'Extract motor power',
    energy_today:'Electrical energy today', energy_month:'Electrical energy this month'};
  const label = key => LABELS[key] || key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  const note = content => ({type:'markdown', content});
  const missing = () => note('No enabled readings in this section. Optional entities may need enabling, or the unit has not reported them.');

  function discover(devices, entities) {
    return devices.filter(d => !d.disabled_by).flatMap(device => {
      const ids = device.identifiers || [];
      const native = ids.find(i => Array.isArray(i) && i[0] === DOMAIN);
      const old = ids.find(i => Array.isArray(i) && i[0] === 'mqtt' && typeof i[1] === 'string' && i[1].startsWith('ventaxia_readonly_'));
      if (!native && !old) return [];
      const unit = native ? native[1] : old[1].slice('ventaxia_readonly_'.length);
      if (typeof unit !== 'string' || !unit) return [];
      const prefix = native ? `${unit}_` : `ventaxia_readonly_${unit}_`;
      const map = {};
      for (const entity of entities) {
        if (entity.device_id !== device.id || entity.disabled_by || entity.hidden_by ||
            !/^(sensor|binary_sensor)\./.test(entity.entity_id || '') ||
            typeof entity.unique_id !== 'string' || !entity.unique_id.startsWith(prefix)) continue;
        const key = entity.unique_id.slice(prefix.length);
        if (KEYS.has(key)) map[key] = entity.entity_id;
      }
      return [{device, unit, legacy:!native, map}];
    });
  }

  function unitViews(unit, allCount, hass, index, showUnit) {
    const e = {...unit.map};
    if (unit.legacy && allCount === 1) {
      for (const [key, entity] of Object.entries(ALIASES)) {
        if (!e[key] && hass.states?.[entity]) e[key] = entity;
      }
    }
    const group = (title, keys, attrs = []) => {
      const rows = keys.filter(k => e[k]).map(k => ({entity:e[k], name:label(k)}));
      for (const [key, attribute, name] of attrs) {
        if (e[key]) rows.push({type:'attribute', entity:e[key], attribute, name});
      }
      return rows.length ? {type:'entities', title, show_header_toggle:false, entities:rows} : missing();
    };
    const graph = (title, keys, hours = 24) => {
      const entries = keys.filter(k => e[k]).map(k => ({entity:e[k], name:label(k)}));
      return entries.length ? {type:'history-graph', title, hours_to_show:hours, entities:entries} : missing();
    };
    const title = unit.device.name_by_user || unit.device.name || 'Ventilation unit';
    const view = (name, cards, icon) => ({title:showUnit ? `${title} · ${name}` : name,
      path:showUnit ? `${unit.device.id}-${name.toLowerCase()}` : name.toLowerCase(), cards});
    const statsNote = unit.legacy
      ? 'Legacy helpers are shown only when exactly one compatible unit exists. Their windows and sampling depend on the helper configuration; history is not migrated. Any sample-span coverage below is approximate, not elapsed-time availability.'
      : 'Native statistics use one-minute samples. Means are means of minute samples; median, standard deviation and percentiles use those samples. P10/P90 remain unavailable below 20 valid samples. Rolling coverage describes sample coverage, not certified performance.';
    const coverageAttrs = [];
    if (unit.legacy && allCount === 1) {
      coverageAttrs.push(['recovery_mean_1h','age_coverage_ratio','Approximate 1 h sample-span coverage'],
        ['recovery_mean_24h','age_coverage_ratio','Approximate 24 h sample-span coverage']);
    }
    return [
      view('Overview', [
        note('## Ventilation telemetry\nReported states and measurements only. Missing or unavailable data does not prove that hardware is off or fault-free.'),
        group('Current operation', ['connection','airflow_preset','override','regulation','bypass_status','frost_status','air_quality']),
        group('Temperatures', ['outdoor_temperature','supply_temperature','indoor_temperature','internal_humidity','external_humidity','co2']),
        graph('Temperature history', ['outdoor_temperature','supply_temperature','indoor_temperature']),
        group('Fans and power', ['supply_rpm','extract_rpm','system_power','supply_motor_power','extract_motor_power','energy_today','energy_month']),
        group('Airflow · unverified units', ['supply_airflow','extract_airflow','supply_measured_airflow','extract_measured_airflow']),
      ], 'mdi:fan'),
      view('Statistics', [
        note('## Apparent temperature recovery\n100 × (supply − outdoor) / (extract − outdoor). The calculation requires |extract − outdoor| ≥ 3 K and valid inputs. It is not certified heat-exchanger efficiency. Interpret alongside reported bypass/frost status; unavailable status does not establish bypass closure. No recovered W or kWh is calculated while airflow units remain unverified.'),
        group('Current calculation', ['recovery_status','recovery_ratio','temperature_lift','available_temperature_difference','remaining_temperature_difference']),
        graph('Recovery ratio history', ['recovery_ratio','recovery_mean_1h','recovery_mean_24h']),
        note(statsNote),
        group('Recovery distribution', ['recovery_mean_1h','recovery_mean_24h','recovery_median_24h','recovery_minimum_24h','recovery_maximum_24h','recovery_sd_24h']),
        ...(e.recovery_samples_24h && (e.recovery_p10_24h || e.recovery_p90_24h) ? [{type:'conditional',
          conditions:[{condition:'numeric_state', entity:e.recovery_samples_24h, above:19}],
          card:group('Percentiles — at least 20 samples', ['recovery_p10_24h','recovery_p90_24h'])}] : []),
        group('Sample quality and coverage', ['recovery_samples_24h','recovery_coverage_1h','recovery_coverage_24h','recovery_oldest_sample','recovery_newest_sample'], coverageAttrs),
        group('Supply temperature lift', ['lift_mean_24h','lift_minimum_24h','lift_maximum_24h']),
      ], 'mdi:chart-line'),
      view('Diagnostics', [
        group('Communication', ['connection','last_telemetry','last_reading','started_at','bridge_started','reconnects','wifi_signal','received_messages','received_mqtt_bytes','sent_mqtt_bytes','ping_replies']),
        group('Reported alert flags', ['faults','warnings','notices'], ['faults','warnings','notices'].flatMap(k => [
          [k,'codes',`${label(k)} codes`], [k,'raw_hex',`${label(k)} raw mask`],
          [k,'unknown_bits_hex',`${label(k)} unknown bits`]])),
        group('Reported override', ['override'], [['override','reported_source_id','Source ID (not a preset)'],
          ['override','reported_started_at','Reported start timestamp'], ['override','requested_duration','Requested duration'],
          ['override','requested_seconds','Requested duration (seconds)']]),
        group('Bypass and frost details', ['bypass_status','frost_status'], [
          ['bypass_status','percent_open','Reported opening (%)'], ['bypass_status','operating_mode','Reported bypass operating mode'],
          ['frost_status','power_raw','Frost power reading — unit unverified'], ['frost_status','usage_raw','Frost usage reading — unit unverified']]),
        note('Alert masks show only what the unit reported. Unknown code bits are preserved. A cause, source ID or requested duration does not establish the effective fan preset.'),
      ], 'mdi:stethoscope'),
      view('Maintenance', [
        group('Filter information', ['filter_1_type','filter_2_type','filter_last_change','filter_interval','filter_1_remaining','filter_2_remaining']),
        group('Service and runtime', ['service_last','service_interval','unit_runtime','supply_motor_runtime','extract_motor_runtime']),
        group('Hardware and software', ['unit_name','model_details','wifi_firmware','wifi_hardware'], [
          ['model_details','firmware_version','Mainboard firmware'], ['model_details','firmware_reported','Raw firmware value'],
          ['model_details','serial_number','Reported serial number'], ['model_details','model_code','Model code'],
          ['model_details','board_revision_id','Board revision ID'], ['model_details','manufacture_date_reported','Reported manufacture date']]),
        note('Dates and intervals are reported values; no service completion, filter reset or firmware action is provided. Motor/unit runtime is displayed in hours by the integration. Unverified maintenance units remain raw.'),
      ], 'mdi:clipboard-text-outline'),
    ];
  }

  class VentaxiaEconiqStrategy extends HTMLElement {
    static getCreateSuggestions() { return {title:'Ventilation', icon:'mdi:fan'}; }
    static async generate(config, hass) {
      let devices, entities;
      try {
        [entities, devices] = await Promise.all([
          hass.callWS({type:'config/entity_registry/list'}),
          hass.callWS({type:'config/device_registry/list'}),
        ]);
        if (!Array.isArray(devices) || !Array.isArray(entities)) throw new Error('Invalid registry response');
      } catch (_) {
        return {title:'Ventilation', views:[{title:'Setup', cards:[note('Unable to read the Home Assistant registries. Check your session permissions and reload this dashboard. No device requests were made.')]}]};
      }
      const all = discover(devices, entities);
      const units = config.device_id ? all.filter(u => u.device.id === config.device_id) : all;
      if (!units.length) return {title:'Ventilation', views:[{title:'Setup', cards:[note(config.device_id
        ? 'The selected Home Assistant device UUID is not a compatible enabled ventilation device. Check strategy.device_id.'
        : 'No compatible enabled ventilation device was found. Set up the native integration or existing read-only MQTT bridge, then reload. The strategy does not connect to or pair a unit.')]}]};
      units.sort((a,b) => a.device.id.localeCompare(b.device.id));
      return {title:'Ventilation', views:units.flatMap((unit,index) => unitViews(unit, all.length, hass, index, units.length > 1))};
    }
  }
  const tag = 'll-strategy-dashboard-ventaxia-econiq';
  if (!customElements.get(tag)) customElements.define(tag, VentaxiaEconiqStrategy);
})();
