# Portable telemetry dashboard

The bundled dashboard strategy generates four read-only tabs for each detected compatible Home Assistant device: **Overview**, **Statistics**, **Diagnostics**, and **Maintenance**. It uses standard Home Assistant cards plus a bundled analytics card, with no external JavaScript libraries, card repositories or CDNs. No personal unit ID, IP address or historic baseline is embedded in the asset.

After the integration is configured, add its bundled module under **Settings → Dashboards → Resources** (enable Advanced mode in your profile if Resources is hidden):

- URL: `/ventaxia_econiq_readonly/dashboard.js?v=0.2.0`
- Resource type: **JavaScript module**

Reload the browser. Create a separate dashboard and put this in its raw configuration:

```yaml
strategy:
  type: custom:ventaxia-econiq
```

Do not replace a dashboard you want to keep. The strategy generates its own views; hand-edited generated cards are not permanent customizations. Home Assistant's custom strategy mechanism is documented in its [official frontend guide](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-strategy/).

To restrict this dashboard to one device, use that device's **Home Assistant registry UUID**, available in its device-page URL:

```yaml
strategy:
  type: custom:ventaxia-econiq
  device_id: YOUR_HOME_ASSISTANT_DEVICE_UUID
```

This selector is not the ventilation serial number or app/Bluetooth device ID. Omit it to discover all compatible devices. Each device gets four separate tabs; entity references are scoped to its registry device and unique ID. Renaming an entity in Home Assistant does not break discovery because the strategy resolves its current entity ID each time it generates the dashboard.

## What appears

- **Overview:** reported preset/cause/bypass/frost state, temperature and humidity readings, histories, fans, electrical power, and explicitly unitless airflow readings where units are unverified.
- **Statistics:** current apparent temperature recovery and temperature differences, history, 1 h and 24 h means, median, minimum/maximum, standard deviation, P10/P90, sample counts, coverage, sample timestamps, and temperature-lift summaries when those entities exist.
- **Diagnostics:** telemetry connection/last reading, reconnect counters, Wi-Fi signal, packet/message counters if provided, alert masks/codes/unknown bits, reported override source/start/duration, bypass opening/mode and unscaled frost attributes.
- **Maintenance:** filter types, dates/intervals/life readings, reported service information, runtime hours, model metadata and firmware versions. There are no acknowledgement, filter-reset, firmware-update or ventilation controls.

Disabled/hidden entities are omitted. Registered but unreported entities remain unavailable through Home Assistant; the dashboard does not create readings or infer that missing hardware is off or healthy. Attribute rows whose data has not been reported may show unavailable. Entire empty sections show a short explanation. If no compatible device exists or registry access fails, a setup message replaces the tabs. Changing configuration, installing optional entities, or resolving permissions may require reloading the dashboard.

The strategy reads `config/entity_registry/list` and `config/device_registry/list` through `hass.callWS`. The analytics card reads Recorder history through `history/history_during_period` when opened or refreshed. Neither sends a unit request or invokes a Home Assistant service. Those list commands and the unique-ID fields are defined by current Home Assistant [entity registry source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/config/entity_registry.py), [registry entry source](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/entity_registry.py), and [device registry source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/config/device_registry.py).

## Interpret recovery statistics carefully

The displayed ratio is **100 × (supply − outdoor) / (extract − outdoor)**, with a guard requiring **|extract − outdoor| ≥ 3 K** and valid inputs. It is apparent temperature recovery, not certified heat-exchanger efficiency. It depends on actual sensor positions, airflow balance, frost protection and bypass operation. The dashboard shows reported bypass/frost information beside the calculation; absent status does not prove that bypass is closed. Do not treat a high percentage alone as a complete performance assessment.

Native rolling statistics use regular one-minute samples. Means average valid minute samples; median, standard deviation and percentile calculations use those samples. P10/P90 cards are hidden until the reported 24 h sample count reaches 20, and the underlying backend also controls their availability. Coverage and oldest/newest timestamps help assess whether a window has enough data. A fresh integration/restart needs time to fill a window; the dashboard does not manufacture missing history or replace it with a dated reference baseline.

The **Ventilation analytics** card plots the last seven days in the Home Assistant time zone. Its six views cover supply temperature lift versus extract–outdoor temperature difference, apparent recovery by preset, humidity/power/lift around Boost transitions, hourly supply lift, matched-weather Normal-mode drift, and daily fan electricity by preset. Drift compares against the preceding seven days in 1 K temperature-difference bins; short history or insufficient overlap leaves gaps. Boost profiles require observed transitions and enough data around them. These are descriptive comparisons, so other differences between days or presets can still explain changes.

The card samples recorded states once per minute and excludes disconnected periods or samples whose last telemetry timestamp is older than three minutes. Missing telemetry is omitted; electricity totals are estimates for observed minutes only. Keep the relevant entities in Recorder to populate the charts. Changing plot reuses the same history without querying the unit.

No recovered thermal W or kWh is computed because installed airflow units/scaling have not been verified. Raw airflow and frost attributes with unverified units are labelled accordingly. Individual motor electrical power is reported in W. System electrical power, where reported with verified W units, is a different quantity from recovered heat.

## Existing MQTT bridge compatibility

The strategy also recognizes devices created by the existing read-only bridge with identifier `ventaxia_readonly_<unitID>` and corresponding entity unique IDs. Keep the bridge installed if you are using those entities; displaying them does not migrate them to the native integration.

Only when **exactly one compatible device is detected** can the strategy use existing shared helpers named `sensor.mvhr_apparent_temperature_recovery`, `sensor.mvhr_supply_temperature_lift`, `sensor.mvhr_available_temperature_difference`, `sensor.mvhr_remaining_temperature_difference`, `sensor.mvhr_recovery_calculation_status`, and `sensor.mvhr_recovery_*` / `sensor.mvhr_lift_*` rolling helpers. Existing `sensor.mvhr_energy_today` and `sensor.mvhr_energy_this_month` can also appear for that single legacy device. These aliases are optional; the dashboard does not create them or assume they belong to one of several units. Selecting one device out of multiple devices does not enable shared aliases.

Legacy helper statistics retain their own configured sampling and windows. If legacy means expose `age_coverage_ratio`, this is shown explicitly as **approximate sample-span coverage**, not elapsed-time availability. Do not compare that estimate directly with native minute-sample coverage without understanding the helper configuration. History/entity IDs are not automatically migrated.

## Optional native electrical energy helpers

Native energy totals are a separate setup choice, not thermal recovery measurements. For a unit with a verified **system electrical power** entity in W:

1. Create Home Assistant's [Integral helper](https://www.home-assistant.io/integrations/integration/) using the discovered system-power entity. Select integration time in hours and metric prefix `k` to obtain kWh from W; choose a method suited to the device's reporting cadence.
2. Create [Utility Meter helpers](https://www.home-assistant.io/integrations/utility_meter/) for daily and monthly cycles using that cumulative energy entity.
3. Add the resulting per-unit helpers to your own cards. The portable native strategy does not guess helper IDs or associate shared legacy energy helpers with native units.

Power integration is an estimate affected by unavailable periods, reporting cadence and integration method. It does not supply independently metered consumption or recovered heat.

## Validation status

Offline Node tests cover native/legacy registry fixtures, renamed entity IDs, multiple devices, explicit selection, missing entities/devices, disabled entities, registry errors and absence of control actions. The four generated tabs have also been rendered against an existing read-only MQTT bridge in Home Assistant. Native platform setup/unload and persisted statistics pass synthetic Home Assistant 2026.10.4 smoke tests in CI. An actual native connection trial on further controller models remains necessary; these checks do not establish compatibility or rendering on every HA version.

Run the offline fixture suite from the repository root:

```sh
node tests/test_dashboard.cjs
```
