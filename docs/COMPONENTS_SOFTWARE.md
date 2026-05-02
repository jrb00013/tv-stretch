# Software stack and components

## Firmware (ESP-IDF)

| Component | Version | Purpose |
|-----------|---------|---------|
| ESP-IDF | 5.2+ | Toolchain, FreeRTOS, Wi‑Fi, NVS, WebSocket client |
| `esp_websocket_client` | IDF built-in | Device ↔ server WebSocket |
| `cJSON` | IDF component | Parse/emit JSON commands |
| `nvs_flash` | IDF | Store WiFi SSID, API key, server URL, room id |

Optional later: `esp_http_client` for OTA, `mqtt_client` if moving to MQTT.

## Server (Python)

| Package | Version (constraint) | Purpose |
|---------|----------------------|---------|
| Python | 3.12+ | Runtime |
| fastapi | ≥0.115 | HTTP + WebSocket API (devices + app presence) |
| uvicorn[standard] | ≥0.30 | ASGI server |
| sqlmodel | ≥0.0.22 | ORM + Pydantic models on SQLite |
| sqlalchemy | 2.x (via sqlmodel) | `EventLog` ordering, diagnostics |
| pydantic | ≥2 | Settings and validation |
| pydantic-settings | ≥2 | `TV_STRETCH_*` env config (`cors_origins`, `api_version`, …) |
| httpx | ≥0.27 | Tests / optional HTTP client |

Dev:

| Package | Purpose |
|---------|---------|
| pytest | Tests |
| pytest-asyncio | Async tests |
| ruff | Lint (optional) |

## Infrastructure

| Service | Purpose |
|---------|---------|
| Docker / Compose | Local all-in-one |
| eclipse-mosquitto | Optional MQTT; not required for default path |

## Mechanical CAD generation

| Tool | Purpose |
|------|---------|
| Python `build123d` | Parametric enclosure; `scripts/generate_enclosure_step.py` |

Install: `pip install build123d` (may require OpenCASCADE system libs; see script docstring).
