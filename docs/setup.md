# Set up existing Econiq telemetry

This community integration reads local telemetry from an already configured Sentinel Econiq using the Vent-Axia Connect/Zirconia MQTT-over-TLS interface. It adds sensors and status indicators. It does not commission, pair, reset, update firmware, change PINs, change Wi-Fi settings, or control ventilation. It does not require Mosquitto.

Evidence and the existing bridge trial concern the Sentinel Econiq controller family. Compatibility with other Vent-Axia products, arbitrary controller/firmware revisions, and Android credential recovery has not been established. The native Home Assistant integration still needs an end-to-end installation trial; offline tests are not a substitute for that trial.

## Gather details without changing the unit

| Home Assistant field | Where to obtain it | What it is not |
| --- | --- | --- |
| Host | Your router's current DHCP/client lease for the ventilation unit, or an already configured resolvable hostname | The router's own address, phone address, or a universal factory address |
| Port | The existing unit's local TLS MQTT endpoint; this implementation defaults to 8883 | A web page or the separate binary protocol port |
| Device ID | The existing Vent-Axia Connect device record/Bluetooth device ID; the recovery tool requires its exact value | Necessarily the printed serial number, product code, friendly description or MAC |
| TLS identity | Existing app options `tcpTlsIdentity`, copied exactly, including any significant characters | A value to guess from the serial number, Wi-Fi SSID, or an example from another unit |
| TLS PSK (hex) | Existing app options `tcpTlsKey`, containing a nonzero even-length hexadecimal byte string | Home Wi-Fi password, Bluetooth/commissioning PIN, QR label, or the database's unrelated `key` column |
| MQTT username/password | Existing known broker credentials if this unit needs them; otherwise leave both blank | Home Wi-Fi credentials or guessed defaults |

Read the router's device details to identify the current address. Use the app's existing device information and compare the known MAC/hostname where available. This guide does not require changing router settings or enabling port forwarding. Home Assistant must already be able to reach that local address. Do not assume every unit uses the same private subnet or IP.

The currently supported subscription prefix is the exact device ID followed by `/`. You supply the ID; the integration constructs the prefix. Do not add `+`, `#`, slashes or a full MQTT topic in the Device ID field. A firmware using a different topic-prefix convention requires further verification.

A unit that has never been paired/configured needs normal manufacturer commissioning outside this integration, following the correct product instructions or an installer. Credential recovery is not a reason to reset, blindly re-pair, or write a PIN to a working installation. If existing credentials are absent, stop and obtain appropriate support rather than guessing.

## Reading the device ID from an existing Bluetooth connection

First check the existing Vent-Axia Connect device information/record. A label can help identify the product and serial number, but the serial number is not necessarily the MQTT device ID, especially after a replacement board.

On the tested controller, a Bluetooth GATT inspector showed the ID in the **read-only** characteristic `673DE933-963B-4298-BFC1-B0CCDADA690A`. Connect to the already accessible unit, find that characteristic, and use **Read** only. Select text/UTF-8 display if available: the returned bytes are ASCII characters forming the ID. A hexadecimal display is an encoding of those characters, not a hexadecimal MQTT ID. Do not use Write, change PINs, re-pair the board, or copy an all-zero characteristic as a TLS key. This characteristic has only been verified on the tested controller family; if it is absent, use the existing app record rather than guessing another characteristic.

The TLS credentials are separate from this ID. They are not shown by reading a serial-number label or a generic Bluetooth PIN field. The recovery method below reads credentials already saved by the paired iPhone app.

## Recover an existing iPhone app record locally

The optional tool reads **one selected device record** from either:

- A completed **unencrypted** Finder backup of an iPhone containing the existing app database.
- A completed, standalone `devices.db` export obtained with a trusted local tool.

It does not contact the unit, connect to a phone, make backups, decrypt backups, install tools, or write to the source database. It locates the database through `Manifest.db` using domain `AppDomain-uk.ventaxia.connect` and a path ending in `devices.db`, then reads the sharded file payload. SQLite opens with `mode=ro&immutable=1` to avoid source locks/journal writes. Use a completed, consistent export, not an active app database that still depends on an outstanding WAL file.

**Keep backup encryption enabled if it is enabled.** Encrypted Finder backups are unsupported by this script. It will stop without requesting a password. If you already use a trusted local backup utility that can export the app's decrypted database, select that exported database instead. Review that utility's privacy/security practices yourself; no particular third-party utility is endorsed here. A backup may contain unrelated private data—do not upload it to this repository or a support issue.

Run from the repository directory on your own computer using Python 3.10 or newer (the recovery script does not require Home Assistant or TLS-PSK support):

```sh
python3 tools/recover_ios_credentials.py \
  --backup '/path/to/completed/backup-directory' \
  --device-id 'YOUR-EXISTING-DEVICE-ID' \
  --output '/path/to/private/new-econiq-credentials.json'
```

Or, with an existing standalone app database export:

```sh
python3 tools/recover_ios_credentials.py \
  --database '/path/to/exported/devices.db' \
  --device-id 'YOUR-EXISTING-DEVICE-ID' \
  --output '/path/to/private/new-econiq-credentials.json'
```

Choose a private output location **outside the repository**, in an existing directory. The script creates a new JSON file with mode `0600`, refuses existing files and symlinks, and prints no credential values. On filesystems that do not enforce Unix permissions, protect the output with your platform's access controls. The JSON contains only `device_id`, `tls_identity`, and `tls_psk_hex`. Open it locally to transfer these three fields to the integration form; it is not automatically imported and is not an integration configuration file. Delete the temporary output when you no longer need it, following your normal handling of secrets. The Home Assistant entry subsequently stores credentials in its local configuration storage—protect HA backups too.

The script reads `devices.id` and `devices.options`. It deliberately excludes descriptions, MACs, unrelated database keys, saved PINs, and home Wi-Fi passwords from the output. Missing/invalid/all-zero TLS keys are rejected. The current app treats an all-zero key as unavailable. If the device ID is missing or ambiguous, verify the exact ID in your existing app record; the script will not choose another device for you.

Android recovery is **untested**. This guide does not prescribe root, ADB data extraction, or app modification. Do not assume an Android APK contains the private per-unit credentials.

## Install and make the first connection

1. Preserve the working setup and note its existing entity names if you want to return to it. This integration does not automatically migrate MQTT entities, dashboards, or recorded history.
2. Install this repository as a HACS custom repository of type **Integration**, using the actual published repository URL, then restart Home Assistant. A local candidate directory cannot be added to HACS as a remote repository. Follow [HACS custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).
3. **Before adding the integration, stop the old bridge/add-on and close other active clients, including the manufacturer app.** Do not run competing telemetry clients during the initial trial. Installing files alone does not require changing the unit.
4. In Home Assistant, open **Settings → Devices & services → Add integration**, choose **Vent-Axia Econiq Read-only**, and enter the gathered connection details. Use the saved TLS identity exactly and the recovered hexadecimal PSK. Leave optional MQTT credentials blank unless known to be needed. Confirm that other clients are stopped.
5. Saving a valid configuration starts the integration's local connection. Form validation itself checks values offline; it does not establish that the endpoint or credentials work. A failed authentication stops automatic attempts instead of trying alternative keys. Review the connection diagnostic and reconfigure the entry with verified details.
6. Confirm reported measurements/statuses before relying on them. Unreported flags remain unknown; they are not invented as clear. Intake and extract humidity are named for airflow position. Reported preset `Low` is not automatically renamed `Quiet`. Airflow readings with unverified units remain unitless.

The native integration requires a Home Assistant Python/OpenSSL runtime with TLS-PSK support (`ssl.HAS_PSK`, Python 3.13+). An unsupported runtime produces a configuration error; changing the unit will not fix that software capability. Some telemetry depends on fitted sensors and firmware. Unsupported/unreported values may remain unavailable.

## Troubleshooting without writes

- **Cannot connect:** check the existing router lease, local reachability, port, and whether another client is connected. Do not expose this port to the internet.
- **Authentication failed:** verify exact saved identity and raw hexadecimal key. A PIN or home Wi-Fi password cannot replace the PSK. Stop repeated guesses.
- **Some readings missing:** confirm the unit actually reports that topic; a missing optional sensor is not proof of a fault. Attach redacted diagnostics, not credentials or databases, to an issue.
- **Need to return to the bridge:** disable/remove the native entry before restarting the old bridge. Entity/history continuity is not promised.

## Primary references

- [Home Assistant integrations](https://www.home-assistant.io/integrations/) and [integration documentation](https://www.home-assistant.io/docs/configuration/integrations/).
- [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/) and [integration repository requirements](https://www.hacs.xyz/docs/publish/integration/).
- [Apple's iPhone/iPad computer-backup guide](https://support.apple.com/en-gb/108809); backup handling is separate from this integration.
- [Vent-Axia product and support site](https://www.vent-axia.com/): obtain the correct Sentinel Econiq and Vent-Axia Connect instructions for your exact product. This community integration is not a manufacturer commissioning tool or manufacturer endorsement.
