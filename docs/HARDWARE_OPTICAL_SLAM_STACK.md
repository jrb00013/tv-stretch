# Optical SLAM, room occupancy, and the coordinator

This document ties **custom PCB / optical sensing**, **house-scale mapping (SLAM or surrogate)**, **person-in-room estimation**, and the **tv-stretch FastAPI server** so TVs follow the user via CEC handoffs.

It is an architecture guide—not a turnkey SLAM implementation. Pick compute where your algorithm requires it (often **SBC class**, not the ESP32 CEC dongle alone).

## Roles

| Layer | Responsibility |
|-------|------------------|
| **Mapping** | Produce a metric or topological map with **room segments** aligned (manually or automatically) to logical `Room` UUIDs already provisioned in the coordinator (`POST /rooms`, bootstrap). |
| **Localization** | Estimate camera / rig pose in the map; derive **which room polygon** contains the user (point-in-polygon or classifier). |
| **Confidence** | Emit a scalar **0–1** confidence before acting (tracking quality, occlusion, multi-hypothesis spread). |
| **Coordinator** | `POST /presence/occupancy` with `room_id` + `confidence`. Above `TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE`, runs the same path as REST/WebSocket handoff → **`command_batch`** to HDMI nodes → **switch inputs / policy** on TVs. |
| **CEC nodes** | Existing **tv-stretch-node** firmware on ESP32-C3 (see KiCad project); unchanged protocol over `/ws/device`. |

## Hardware paths (examples)

### A — Wearable / handheld rig (RGB-D or stereo + IMU)

- **Compute:** Raspberry Pi 5 / Jetson Orin Nano / x86 NUC for heavy VIO/SLAM if needed.
- **Sensors:** Stereo pair or RGB-D (e.g. Intel RealSense class), **IMU** for scale and gravity alignment.
- **Radio:** Wi‑Fi to LAN; HTTPS or WSS to coordinator (browser-grade TLS via reverse proxy).
- **Custom PCB:** Sensor bracket + **USB3** hub + IMU on **I²C** to the SBC; optional battery gauge.

### B — Fixed ceiling / wall optical nodes (no full SLAM on device)

- **Per-room** depth blob or low-res occupancy grid fused on a **home server**; server-side SLAM optional.
- **Optical:** ToF arrays (e.g. **VL53L5CX**), mmWave presence (non-optical but common pairing), or narrow-FOV IR grids.
- **MCU:** ESP32-S3 for aggregation + Wi‑Fi; **not** responsible for full-house SLAM unless map is trivial.

### C — Cartographer-style LiDAR + odometry (mobile base)

- **2D LiDAR** + wheel odometry or IMU; output pose to mapping stack; room IDs assigned when crossing thresholds / doors (still map to coordinator `room_id` UUIDs).

## Map ↔ server contract

1. **Provision rooms** in the coordinator (`POST /bootstrap/home-with-rooms` or `/rooms`) so each physical room has a **stable UUID**.
2. **Upload spatial metadata** (optional but recommended): `POST /spatial/maps` with JSON under `slam.v1` (or your schema string). Store polygons, adjacency, or vendor SLAM export references for debugging and alignment.
3. **Runtime:** localization stack selects **one `room_id`** + **confidence** → `POST /presence/occupancy`.

Payload shape is intentionally loose: your SLAM stack owns the JSON under `payload`; the server stores it opaquely for tooling.

## Software integration

- **Auth:** Same **`X-Control-Token`** as other home APIs (treat like a password on TLS inside LAN).
- **Threshold:** `TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE` (default **0.65**) suppresses flaky switches.
- **Displays:** Handoff path already issues **CEC** commands via nodes; tune coordinator policies (`standby_others`) for multi-TV homes.

## Physical / safety

- **HDMI CEC** varies by TV vendor—expect lab tuning (see [CEC_NOTES.md](CEC_NOTES.md)).
- **Privacy:** cameras and continuous localization carry consent and retention obligations—document your policy.

## Related docs

- [COMPONENTS_HARDWARE.md](COMPONENTS_HARDWARE.md) — tv-stretch-node BOM-level parts.
- [BOM.md](BOM.md) — optional presence/SLAM companion bill of materials.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system diagram including occupancy path.
- [API.md](API.md) — `/spatial/*`, `/presence/occupancy`.
