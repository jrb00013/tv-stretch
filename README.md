# tv-stretch

Room-aware TV coordination: a **FastAPI** server plus **ESP32** nodes that attach to each TV’s HDMI CEC bus. The stack orchestrates which room is “active” and sends control-plane commands (power, input, CEC keys). It does **not** sync protected streaming playheads; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

| Path | Purpose |
|------|---------|
| `docs/` | Architecture, BOM, component datasheets notes, CEC, mechanical |
| `hardware/kicad/` | KiCad 8 schematic and PCB |
| `hardware/cad/` | Enclosure source and `exports/enclosure.step` |
| `firmware/tv-stretch-node/` | ESP-IDF firmware (ESP32-C3 target) |
| `server/` | FastAPI + SQLite (SQLModel), WebSocket device gateway |

## Quickstart (API)

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export TV_STRETCH_DATABASE_URL="sqlite:///./tv_stretch.db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/` (redirects to the control UI) or `http://localhost:8000/docs` for OpenAPI.

**Browser control UI** (`/ui/`): sticky section nav, API **version chip** (from `/health/ready`), **diagnostics** (`GET /diagnostics/overview` and per-home **live** sockets), **spatial maps** + **occupancy** lab (`/spatial/maps`, `POST /presence/occupancy`), dark-themed **bootstrap**, authenticated **REST**, **app** and **device** WebSocket labs, **log** export (download + **Ctrl+Shift+S**) and clear (**Ctrl+Shift+L**). Assets: `server/static/css/`, `server/static/js/`, `server/static/assets/favicon.svg`. Full protocol: [docs/API.md](docs/API.md). Provisioning + OTA: [docs/PROVISIONING_AND_OTA.md](docs/PROVISIONING_AND_OTA.md).

Server package version is **0.6.1** (`pyproject.toml` / `TV_STRETCH_*` defaults).

### Coordinator capabilities

| Area | What it does | Key routes |
|------|--------------|------------|
| Handoff | REST / app-WebSocket / sensor-driven handoffs, standby of other TVs | `POST /sessions/handoff`, `/ws/app` |
| Delivery | Every `command_batch` tracked to node acks, exponential-backoff retry, dead letters | `GET /sessions/batches` |
| Replay safety | `Idempotency-Key` on the mutating session endpoints | `Idempotency-Key:` header |
| Room policy | Per-room volume cap, mute-on-handoff, preferred input, standby opt-out | `GET/PUT/DELETE /rooms/{id}/policy` |
| Quiet hours | Per-home do-not-disturb window; people can override, sensors cannot | `GET/PUT/DELETE /quiet-hours` |
| Presence tuning | Dwell hysteresis + vacancy release so sensors do not thrash the TVs | `GET /presence/hysteresis` |
| Content | Catalogue behind `content_ref`, play stats, now-playing | `GET /content`, `GET /sessions/now-playing` |
| Firmware | Per-node rollout status against a target version | `GET/PUT/DELETE /ota/rollout` |
| Events | Time-window queries, cursor pagination, age-based pruning | `GET/DELETE /sessions/events` |
| Webhooks | Signed (HMAC) outbound events with retry and delivery stats | `GET/POST /webhooks` |
| Metrics | Prometheus text format: HTTP, sockets, batch depth, node health | `GET /metrics` |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE` | `0.65` | Minimum occupancy confidence to trigger a handoff |
| `TV_STRETCH_PRESENCE_DWELL_SECONDS` | `0` (off) | Continuous occupancy required before a sensor-driven handoff |
| `TV_STRETCH_PRESENCE_DWELL_MAX_GAP_SECONDS` | `30` | Longer reporting gap restarts the dwell timer |
| `TV_STRETCH_PRESENCE_RELEASE_SECONDS` | `0` (off) | Sustained vacancy in the active room → TVs stand by |
| `TV_STRETCH_DATABASE_URL` | `sqlite:///./tv_stretch.db` | SQLAlchemy database URL |
| `TV_STRETCH_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `TV_STRETCH_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Base URL used in OTA manifest URLs |
| `TV_STRETCH_OTA_FIRMWARE_PATH` / `_VERSION` | — / `0.6.1` | Hosted firmware binary and the version it reports |
| `TV_STRETCH_MQTT_ENABLED` / `_BROKER_URL` / `_BROKER_PORT` / `_PREFIX` | `true` / `localhost` / `1883` / `tvstretch` | Optional MQTT mirroring |

Quiet hours and room policies are per-home rows configured over the API, not env vars.
Full protocol and semantics: [docs/API.md](docs/API.md).

From the repo root, `./scripts/dev.sh` or `make dev` runs uvicorn with a local SQLite DB (after `pip install -e ".[dev]"` in `server/`).

Optional env vars: copy `server/.env.example` → `server/.env`. Example curls for spatial + occupancy: `scripts/spatial-presence-examples.sh` (set `TOKEN`, optionally `BASE`).

**Breaking note (0.2+):** `Home` rows require `control_token`. Delete old `tv_stretch.db` or recreate homes after upgrading.

### Docker

```bash
docker compose up --build
```

API on `http://localhost:8000`. Mosquitto is included for optional MQTT experiments; the default device transport is WebSocket.

## Firmware

Requires [ESP-IDF](https://docs.espressif.com/projects/esp-idf/) v5.2+.

```bash
cd firmware/tv-stretch-node
idf.py set-target esp32c3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

Set WiFi and server URL via `idf.py menuconfig` → **TV Stretch Node Configuration**, or NVS keys documented in `firmware/tv-stretch-node/README.md`.

## Hardware

- KiCad project: `hardware/kicad/tv-stretch-node/`
- Gerber export: see `hardware/kicad/tv-stretch-node/exports/README.md`
- Enclosure STEP: `hardware/cad/enclosure/exports/enclosure.step` (regenerate with `scripts/generate_enclosure_step.py` if needed)

## License

MIT — see [LICENSE](LICENSE).
