# tv-stretch-node Firmware Architecture

**Target:** ESP32-C3 (RISCV 32-bit single-core, 400 KB SRAM, 4 MB flash)  
**Framework:** ESP-IDF 5.2+  
**Protocol:** CEC bit-bang on GPIO + WebSocket JSON control-plane

---

## 1. System Overview

Each TV in a room gets an ESP32-C3 node wired to its HDMI CEC pin (pin 13). The node connects to the coordinator server via WebSocket and executes HDMI-CEC commands over a bit-banged GPIO line. There is no HDMI input switching or EDID emulation — this is purely a control-plane bridge.

```
┌─────────────────┐     WebSocket      ┌──────────────────┐
│  Coordinator    │ ◄────────────────► │  ESP32-C3 Node   │
│  (FastAPI)      │   JSON/v1 protocol │  (tv-stretch-node)│
└─────────────────┘                    └────────┬─────────┘
                                                │ GPIO (open-drain)
                                                ▼
                                        ┌──────────────────┐
                                        │  TV HDMI CEC pin │
                                        └──────────────────┘
```

---

## 2. Boot Sequence

```
Power-on / Reset
    │
    ├── nvs_flash_init()
    │       └── NVS recovery (erase + retry if corrupted)
    │
    ├── led_init()
    │       └── Configure status LED GPIO as output
    │
    ├── esp_netif_init() + esp_event_loop_create_default()
    │
    ├── [CONFIG_TVS_HTTP_PROVISIONING] ──Provisioning check──┐
    │       └── NVS provisioned?                              │
    │           ├── NO  → tvs_prov_run_http_setup()           │
    │           │         (SoftAP + HTTP server, blocks)      │
    │           └── YES → continue                            │
    │                                                         │
    ├── Read NVS (tvstretch namespace)                       │
    │       ├── wifi_ssid / wifi_pass                        │
    │       ├── ws_url / api_key                             │
    │       └── room_id / home_id                            │
    │                                                         │
    ├── tvs_wifi_start_sta(ssid, pass)                       │
    │       └── Event-driven STA connect (WPA2)              │
    │                                                         │
    ├── tvs_wifi_wait_connected(timeout=60s)                 │
    │       └── Blocks until got IP                         │
    │                                                         │
    ├── tvs_cec_init(CEC_GPIO)                               │
    │       └── GPIO open-drain, pull-up enabled             │
    │                                                         │
    ├── [CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT]                  │
    │       └── Spawns boot_ota_task (5s delay + manifest)   │
    │                                                         │
    ├── tvs_ws_start(ws_url, api_key, home_id, room_id)      │
    │       └── WebSocket client with auto-reconnect         │
    │                                                         │
    ├── Send hello JSON                                      │
    │       └── {"v":1, "type":"hello", "node":{...}}       │
    │                                                         │
    └── Spawn heartbeat_task (every 25s)                    │
            └── {"v":1, "type":"heartbeat"}                  │
```

---

## 3. Module Map

| Module | File(s) | Purpose |
|--------|---------|---------|
| **Main** | `app_main.c` | Boot sequence, command dispatch, message routing |
| **Protocol** | `proto/tv_stretch_proto.h` | Constants (`TVS_PROTO_VER`), message type enum, command struct |
| **CEC Driver** | `cec/cec_bitbang.c`, `cec/cec_bitbang.h` | Bit-banged CEC TX using GPTimer delay |
| **WiFi** | `net/tvs_wifi.c`, `net/tvs_wifi.h` | STA mode with event-driven connect/reconnect |
| **WebSocket** | `net/ws_client.c`, `net/ws_client.h` | esp_websocket_client wrapper, header injection |
| **OTA** | `ota/tvs_ota.c`, `ota/tvs_ota.h` | HTTP/HTTPS OTA from URL or manifest JSON |
| **Provisioning** | `prov/prov_http.c`, `prov/prov_http.h` | SoftAP + HTTP capture portal |
| **NVS** | `prov/tvs_nvs.c`, `prov/tvs_nvs.h` | Provisioned-state check (`nvs_get_u8`) |

---

## 4. CEC Driver Design

The CEC driver in `cec_bitbang.c` implements a **transmit-only** subset of the HDMI-CEC physical layer.

### Timing (microseconds)

| Signal | Low (us) | High (us) |
|--------|----------|-----------|
| Start bit | 3700 | 800 |
| Logic 0 | 1500 | 900 |
| Logic 1 | 600 | 600 |

### Frame format

```
[Start Bit] [Header Byte: initiator<<4 | destination] [Data Bytes...] [EOM bit per byte]
```

- Each byte is 8 bits LSB-first + 1 EOM bit + ACK slot
- The follower is expected to pull the ACK slot low; this driver uses a fixed delay for the ACK window
- No arbitration or retry logic (single-talker topology assumed)

### Supported CEC opcodes

| Command | Opcode | Payload |
|---------|--------|---------|
| `<Active Source>` | 0x82 | 2-byte physical address |
| `<Standby>` | 0x36 | None |
| `<User Control Pressed>` | 0x44 | 1-byte key code |
| `<Set Stream Path>` | 0x86 | 2-byte physical address |
| Broadcast ping | 0x83 | None |

---

## 5. WebSocket Protocol

### Connection

The node connects to `ws://<coordinator>/ws/device` with custom HTTP headers:

```
Authorization: Bearer <api_key>
X-TV-Stretch-Home: <home_uuid>
X-TV-Stretch-Room: <room_uuid>
```

### Messages (all JSON with `"v": 1`)

**Node → Server:**

| Type | Frequency | Payload |
|------|-----------|---------|
| `hello` | Once on connect | `{node: {room_id, home_id, fw}}` |
| `heartbeat` | Every 25s | None |
| `ack` | After each batch | `{batch_id, ok}` |
| `event` | On CEC RX / errors | `{payload: {kind, raw}}` |

**Server → Node:**

| Type | Purpose |
|------|---------|
| `command_batch` | Array of commands with batch_id |

---

## 6. Command Dispatch

`handle_command()` in `app_main.c` dispatches by `cmd` string:

| cmd | Action |
|-----|--------|
| `noop` | Log, no-op |
| `policy` | Log (server-side enforcement) |
| `ota_pull` | Start OTA from URL or manifest |
| `cec_broadcast_ping` | Send 0x83 frame |
| `cec_standby` | Send `<Standby>` (0x36) |
| `cec_active_source` | Send `<Active Source>` (0x82 + addr) |
| `cec_user_control` | Send `<User Control Pressed>` (0x44 + key) |
| `cec_set_stream_path` | Send `<Set Stream Path>` (0x86 + addr) |
| `cec_send_raw` | Send arbitrary CEC frame from byte array |

After processing all commands in a batch, the node sends an `ack` back to the coordinator.

---

## 7. OTA Update

Two mechanisms:

1. **Direct URL:** `ota_pull` with `{"url": "http://.../firmware.bin"}`  
   Downloads and applies via `esp_https_ota`

2. **Manifest URL:** `ota_pull` with `{"manifest_url": "http://.../manifest.json"}`  
   Fetches `{"version": "x.y.z", "url": "..."}`, optionally skips if version matches `CONFIG_TVS_FW_VERSION`

OTA uses dual-OTA partition table (2 × 1.66 MB slots). On success, `esp_restart()` boots into the new slot.

---

## 8. Provisioning

Optional HTTP-based provisioning (disabled by default, enable via `TVS_HTTP_PROVISIONING` Kconfig):

1. On first boot (NVS `provisioned != 1`), starts SoftAP `tv-stretch-setup`
2. HTTP server on `192.168.4.1:80` serves a capture portal form
3. POST `/save` writes WiFi/coordinator settings to NVS and sets `provisioned=1`
4. Device reboots into normal operation

---

## 9. Memory & Task Layout

| Task | Stack | Priority | Function |
|------|-------|----------|----------|
| `main` | (default) | 1 | Boot sequence, then idle |
| `boot_ota` | 8192 | 3 | Boot-time OTA check (optional) |
| `ota` | 10240 | 5 | OTA download task |
| `hb` | 4096 | 5 | Heartbeat sender |
| WiFi/WS | (IDF internal) | — | Event loop, WebSocket RX |

---

## 10. Build & Test

```bash
# Standard build
idf.py set-target esp32c3
idf.py menuconfig
idf.py build

# Flash and monitor
idf.py -p /dev/ttyUSB0 flash monitor

# Unity unit tests (on-target)
idf.py test

# Integration tests (requires pytest-embedded)
pip install pytest-embedded-serial-esp
pytest firmware/tv-stretch-node/pytest_tv_stretch_node.py
    --embedded-services esp,idf
    --app firmware/tv-stretch-node/build
```

---

## 11. Configuration (Kconfig)

See `main/Kconfig.projbuild` for all options. Key settings:

| Option | Default | Notes |
|--------|---------|-------|
| `TVS_CEC_GPIO` | 4 | CEC output pin |
| `TVS_STATUS_LED_GPIO` | 8 | Activity LED pin |
| `TVS_FW_VERSION` | 0.3.0 | Semver reported to coordinator |
| `TVS_HTTP_PROVISIONING` | n | Enable SoftAP setup portal |
| `TVS_OTA_AUTO_CHECK_ON_BOOT` | n | Auto-OTA on version mismatch |
