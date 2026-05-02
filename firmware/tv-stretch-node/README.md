# tv-stretch-node firmware

ESP-IDF **5.2+** project targeting **ESP32-C3**.

## Build

```bash
export IDF_PATH=/path/to/esp-idf
. $IDF_PATH/export.sh
cd firmware/tv-stretch-node
idf.py set-target esp32c3
idf.py menuconfig   # TV Stretch Node Configuration
idf.py build
```

## Flash

```bash
idf.py -p /dev/ttyUSB0 flash monitor
```

## NVS keys (optional overrides)

Use `nvs_set_str` via a small flasher or `idf.py nvs-set` if configured:

| Key | Purpose |
|-----|---------|
| `wifi_ssid` | WiFi SSID |
| `wifi_pass` | WiFi password |
| `ws_url` | `ws://host:8000/ws/device` |
| `api_key` | Device bearer token |
| `room_id` | UUID string |
| `home_id` | UUID string |

Namespace: `tvstretch`.

## Features (0.2)

- Wi‑Fi STA with **wait-for-IP** before WebSocket connect.
- **Status LED** pulse on each `command_batch` (Kconfig `TVS_STATUS_LED_ENABLE` / GPIO).
- CEC commands: `cec_broadcast_ping`, `cec_active_source` (opcode `0x82` + physical address), `cec_standby`, `cec_send_raw`, `policy` (logged), `noop`.
- Sends **ack** after each batch with server `batch_id`.
- Reports `CONFIG_TVS_FW_VERSION` in `hello`.

## WebSocket protocol

See [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) and [docs/API.md](../../docs/API.md). Messages are JSON with `"v":1`.
