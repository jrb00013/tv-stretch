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

**Browser control UI** (`/ui/`): dark-themed lab for ping/ready, one-click **bootstrap** (`POST /bootstrap/home-with-rooms`), authenticated **REST** (rooms, session, handoff with `standby_others`, events, node health), optional **localStorage** for the control token, **app WebSocket** (`/ws/app`: presence, `get_session`, ping) and a **device simulator** for `/ws/device` (query auth, auto-ack, hello/heartbeat) so you can exercise full handoff → command_batch → ack without hardware. Full protocol: [docs/API.md](docs/API.md). Provisioning + OTA: [docs/PROVISIONING_AND_OTA.md](docs/PROVISIONING_AND_OTA.md).

From the repo root, `./scripts/dev.sh` or `make dev` runs uvicorn with a local SQLite DB (after `pip install -e ".[dev]"` in `server/`).

The browser UI under `server/static/` is split into `css/app.css` and ES modules in `server/static/js/` (entry `main.js`) instead of a single huge HTML file.

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
