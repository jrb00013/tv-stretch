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

## 2. State Machine

The node lifecycle is driven by a finite state machine in `core/tvs_state.c`:

```
COLD_START
    │
    ├── PROVISIONING ──── (SoftAP + HTTP portal, blocks)
    │
    ├── WIFI_CONNECT ──── WiFi STA started
    │       │
    │       └── WIFI_WAIT ──── waiting for DHCP
    │               │
    │               └── WS_CONNECT ──── WebSocket client started
    │                       │
    │                       ├── WS_CONNECTED ──── hello sent, ready
    │                       │
    │                       └── DISCONNECTED ──── WS dropped, reconnecting
    │
    ├── ERROR ──── unrecoverable fault
    │
    └── DEEP_SLEEP ──── low-power mode (future)
```

State transitions drive LED patterns and enable/disable subsystems.

---

## 3. Boot Sequence

```
app_main()
    │
    ├── nvs_flash_init()
    │       └── NVS recovery (erase + retry if corrupted)
    │
    ├── tvs_led_init() ──── LED task starts (BOOT pattern)
    │
    ├── tvs_watchdog_init() ──── esp_task_wdt, 30s timeout
    │
    ├── tvs_state_init() ──── state machine + change callback
    │
    ├── tvs_cec_init() ──── CEC TX GPIO (open-drain)
    ├── tvs_cec_rx_init() ──── CEC RX GPIO interrupt + ring buffer
    ├── tvs_cec_proto_init() ──── CEC protocol parser
    │
    ├── tvs_cmd_queue_init() ──── command queue with retry
    ├── tvs_health_init() ──── health counters
    │
    ├── esp_netif_init() + esp_event_loop_create_default()
    │
    ├── [CONFIG_TVS_HTTP_PROVISIONING] ──Provisioning check──┐
    │       └── NVS provisioned?                              │
    │           ├── NO  → tvs_prov_run_http_setup()           │
    │           │         (state → PROVISIONING)              │
    │           └── YES → continue                            │
    │                                                         │
    ├── Read NVS (tvstretch namespace)                       │
    │       ├── wifi_ssid / wifi_pass                        │
    │       ├── ws_url / api_key                             │
    │       ├── room_id / home_id                            │
    │                                                         │
    ├── tvs_wifi_start_sta(ssid, pass)                       │
    │       └── state → WIFI_CONNECT                         │
    │                                                         │
    ├── tvs_cec_rx_start() ──── enable CEC RX ISR            │
    │                                                         │
    ├── cmd_queue_task ──── processes queued commands         │
    │                                                         │
    ├── [CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT]                  │
    │       └── Spawns boot_ota_task (optional)              │
    │                                                         │
    ├── tvs_ws_start() ──── WebSocket client                 │
    │       └── state → WS_CONNECT                            │
    │       └── on_connect → state → WS_CONNECTED + send hello│
    │                                                         │
    ├── heartbeat_task ── every 25s if WS_CONNECTED          │
    ├── health_task ──── every 60s logs telemetry            │
    │                                                         │
    └── main loop ──── feeds watchdog every 5s               │
```

---

## 4. Module Map

| Module | File(s) | Purpose |
|--------|---------|---------|
| **Main** | `app_main.c` | Boot sequence, task spawning, state wiring |
| **State Machine** | `core/tvs_state.c`, `core/tvs_state.h` | Finite state machine with change callback |
| **Command Queue** | `core/tvs_cmd_queue.c`, `core/tvs_cmd_queue.h` | Retry-capable command queue with ACK/NACK |
| **Protocol** | `proto/tv_stretch_proto.h` | Constants (`TVS_PROTO_VER`), message type enum, command struct |
| **CEC TX** | `cec/cec_bitbang.c`, `cec/cec_bitbang.h` | Bit-banged CEC transmit using esp_rom_delay_us |
| **CEC RX** | `cec/cec_rx.c`, `cec/cec_rx.h` | GPIO interrupt edge capture + ring buffer + software decode |
| **CEC Proto** | `cec/cec_proto.c`, `cec/cec_proto.h` | CEC opcode parsing, device discovery, bus scan |
| **WiFi** | `net/tvs_wifi.c`, `net/tvs_wifi.h` | STA mode with event-driven connect/reconnect |
| **WebSocket** | `net/ws_client.c`, `net/ws_client.h` | esp_websocket_client wrapper, header injection, connect callback |
| **OTA** | `ota/tvs_ota.c`, `ota/tvs_ota.h` | HTTP/HTTPS OTA from URL or manifest JSON |
| **LED** | `sys/tvs_led.c`, `sys/tvs_led.h` | LED pattern engine (BOOT, CONNECTING, CONNECTED, etc.) |
| **Health** | `sys/tvs_health.c`, `sys/tvs_health.h` | Telemetry counters (RSSI, frame counts, heap, uptime) |
| **Watchdog** | `sys/tvs_watchdog.c`, `sys/tvs_watchdog.h` | ESP-TASK-WDT wrapper |
| **Provisioning** | `prov/prov_http.c`, `prov/prov_http.h` | SoftAP + HTTP capture portal |
| **NVS** | `prov/tvs_nvs.c`, `prov/tvs_nvs.h` | Provisioned-state check (`nvs_get_u8`) |

---

## 5. CEC Driver Design

### 5.1 Transmit (`cec_bitbang.c`)

Implements the HDMI-CEC physical layer using bit-banged GPIO with spin-loop timing.

#### Timing (microseconds)

| Signal | Low (us) | High (us) |
|--------|----------|-----------|
| Start bit | 3700 | 800 |
| Logic 0 | 1500 | 900 |
| Logic 1 | 600 | 600 |

#### Frame format

```
[Start Bit] [Header Byte: initiator<<4 | destination] [Data Bytes...] [EOM bit per byte]
```

- Each byte is 8 bits LSB-first + 1 EOM bit + ACK slot
- The follower is expected to pull the ACK slot low; this driver uses a fixed delay for the ACK window
- No arbitration or retry logic (single-talker topology assumed)
- Before each frame, `tvs_cec_set_tx_active(true)` suppresses RX echo detection

### 5.2 Receive (`cec_rx.c`)

GPIO interrupt-based edge capture with software bit decoding.

- GPIO `INTR_ANYEDGE` ISR pushes timestamps into a 128-entry ring buffer
- Dedicated decode task (`cec_rx`) pops edges and reconstructs bits/frames
- Start bit detection (`low=3000-4500us, high=600-1100us`) triggers frame assembly
- Frame timeout after 5ms of bus inactivity
- `s_tx_active` flag suppresses echo during local TX
- Completed frames are passed to the registered callback (`tvs_cec_rx_cb`)
- Frame counter exposed for health telemetry

### 5.3 Protocol Layer (`cec_proto.c`)

Parses received CEC frames and maintains a device table:

- Tracks 16 logical addresses with physical address, device type, OSD name, vendor ID, power status
- Responds to `REPORT_PHYSICAL_ADDR`, `REPORT_POWER_STATUS`, `SET_OSD_NAME`, `DEVICE_VENDOR_ID`, `ACTIVE_SOURCE`, `STANDBY`
- Bus scan: polls all 15 addresses with `GIVE_PHYSICAL_ADDR`, `GIVE_OSD_NAME`, `GIVE_DEVICE_POWER_STATUS`
- Frames that are not protocol-internal are forwarded to the application callback

---

## 6. WebSocket Protocol

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

## 7. Command Dispatch

Commands arrive in `command_batch` messages and are enqueued into `tvs_cmd_queue`. The `cmd_queue_task` dequeues and dispatches them:

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
| `scan_bus` | Initiate CEC bus device discovery |

After all commands in a batch are processed, an `ack` is sent back.

---

## 8. LED Patterns

| State | Pattern |
|-------|---------|
| BOOT | Fast blink (200ms on/off) |
| CONNECTING | Slow blink (50ms on, 950ms off) |
| CONNECTED | Long pulse (100ms on, 2900ms off) |
| COMMAND | Quick flash (40ms on) |
| ERROR | Rapid blink (100ms on/off) |
| OTA | Toggle (500ms on/off) |
| OFF | Solid off |

---

## 9. Health Telemetry

The `health_task` logs every 60s (configurable via `TVS_HEALTH_INTERVAL`):

- Uptime in seconds
- WiFi RSSI
- CEC TX/RX frame counts
- WebSocket reconnection count
- Command queue depth
- Free heap / minimum free heap

---

## 10. OTA Update

Two mechanisms:

1. **Direct URL:** `ota_pull` with `{"url": "http://.../firmware.bin"}`  
   Downloads and applies via `esp_https_ota`

2. **Manifest URL:** `ota_pull` with `{"manifest_url": "http://.../manifest.json"}`  
   Fetches `{"version": "x.y.z", "url": "..."}`, optionally skips if version matches `CONFIG_TVS_FW_VERSION`

OTA uses dual-OTA partition table (2 × 1.66 MB slots). On success, `esp_restart()` boots into the new slot.

---

## 11. Provisioning

Optional HTTP-based provisioning (disabled by default, enable via `TVS_HTTP_PROVISIONING` Kconfig):

1. On first boot (NVS `provisioned != 1`), starts SoftAP `tv-stretch-setup`
2. HTTP server on `192.168.4.1:80` serves a capture portal form
3. POST `/save` writes WiFi/coordinator settings to NVS and sets `provisioned=1`
4. Device reboots into normal operation

---

## 12. Watchdog

ESP-TASK-WDT with configurable timeout (default 30s). The main loop feeds every 5s. If any task hangs for longer than the timeout, the watchdog panics and triggers a reboot.

---

## 13. Memory & Task Layout

| Task | Stack | Priority | Function |
|------|-------|----------|----------|
| `main` | (default) | 1 | Boot, then watchdog feed loop |
| `tvs_led` | 2048 | 1 | LED pattern oscillator |
| `cec_rx` | 4096 | 8 | CEC edge decode |
| `cmdq` | 4096 | 6 | Command queue dispatch |
| `boot_ota` | 8192 | 3 | Boot-time OTA check (optional) |
| `ota` | 10240 | 5 | OTA download task |
| `hb` | 3072 | 5 | Heartbeat sender |
| `health` | 3072 | 2 | Telemetry logger |
| WiFi/WS | (IDF internal) | — | Event loop, WebSocket RX |

---

## 14. Build & Test

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
pytest firmware/tv-stretch-node/pytest_tv_stretch_node.py \
    --embedded-services esp,idf \
    --app firmware/tv-stretch-node/build
```

---

## 15. Configuration (Kconfig)

See `main/Kconfig.projbuild` for all options. Key settings:

| Option | Default | Notes |
|--------|---------|-------|
| `TVS_CEC_LOGICAL_ADDR` | 4 | CEC logical address claimed on bus |
| `TVS_CEC_GPIO` | 4 | CEC output pin |
| `TVS_CEC_RX_ENABLE` | y | Enable CEC receive path |
| `TVS_STATUS_LED_GPIO` | 8 | Activity LED pin |
| `TVS_HEALTH_INTERVAL` | 60s | Health telemetry log interval |
| `TVS_WATCHDOG_TIMEOUT` | 30s | Task watchdog timeout |
| `TVS_FW_VERSION` | 0.4.0 | Semver reported to coordinator |
| `TVS_HTTP_PROVISIONING` | n | Enable SoftAP setup portal |
| `TVS_OTA_AUTO_CHECK_ON_BOOT` | n | Auto-OTA on version mismatch |
