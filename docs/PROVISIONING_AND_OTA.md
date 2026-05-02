# Provisioning and OTA

## HTTP provisioning (ESP32)

Enable **Component config → TV Stretch Node Configuration → First-boot SoftAP + HTTP provisioning UI**.

On first boot (NVS key `provisioned` ≠ 1), the device starts an access point:

- SSID / password: Kconfig `TVS_PROV_AP_SSID` / `TVS_PROV_AP_PASS` (defaults `tv-stretch-setup` / `tvstretch1`).
- Join from a phone or laptop, open **http://192.168.4.1**
- Submit Wi-Fi credentials, `ws_url` (`ws://…/ws/device`), node `api_key`, `home_id`, `room_id`.
- Device writes NVS namespace `tvstretch`, sets `provisioned=1`, reboots into STA mode.

Disable provisioning in production firmware builds once nodes are flashed, or rely on pre-provisioned NVS.

## OTA partitions

`firmware/tv-stretch-node/partitions.csv` defines **dual OTA** app slots. Flash with `idf.py flash` as usual; the running image must be linked for OTA (see ESP-IDF OTA docs).

`sdkconfig.defaults` sets `CONFIG_ESP_HTTPS_OTA_ALLOW_HTTP=y` so **LAN HTTP** URLs work. Do not expose unauthenticated OTA endpoints on the public internet.

## Coordinator OTA

See [server/ota/README.md](../server/ota/README.md). Configure `TV_STRETCH_OTA_FIRMWARE_PATH` and `TV_STRETCH_PUBLIC_BASE_URL`.

## Device-side triggers

- **Boot:** optional `TVS_OTA_BOOT_MANIFEST_URL` + `TVS_OTA_AUTO_CHECK_ON_BOOT` (off by default).
- **Command:** `ota_pull` with `url` or `manifest_url` (see server README).

Firmware version string comes from Kconfig `TVS_FW_VERSION` and is compared to manifest `version` when using `only_if_version_differs`.
