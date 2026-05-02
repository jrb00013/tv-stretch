# HTTP and WebSocket API

Base URL: `http://localhost:8000` (or your host). OpenAPI UI: `/docs`.

## Authentication model

- **Nodes** (TV hardware): `Authorization: Bearer <node_api_key>` and `X-TV-Stretch-Home: <home_uuid>` on **`/ws/device`**.
- **Apps** (phone / automation): `Authorization: Bearer <home.control_token>` and `X-TV-Stretch-Home: <home_uuid>` on **`/ws/app`**. The `control_token` is returned when you create a home (`POST /homes`) or when you rotate it (`POST /homes/{id}/rotate-control-token`).

REST endpoints for provisioning are currently **unauthenticated** (home LAN / dev). Put the API behind a reverse proxy and TLS before exposing to the internet.

## Bootstrap a home

```bash
curl -sS -X POST http://localhost:8000/bootstrap/home-with-rooms \
  -H 'Content-Type: application/json' \
  -d '{"home_name":"loft","room_names":["living","kitchen","bedroom"]}'
```

Save `home.control_token` and each `rooms[].id`.

## Register a node per TV

```bash
curl -sS -X POST http://localhost:8000/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{"home_id":"<HOME_UUID>","room_id":"<ROOM_UUID>","name":"living-tv"}'
```

Save `api_key` into firmware NVS key `api_key` (or Kconfig for dev).

## Handoff (REST)

```bash
curl -sS -X POST http://localhost:8000/sessions/handoff \
  -H 'Content-Type: application/json' \
  -d '{"home_id":"<HOME_UUID>","active_room_id":"<ROOM_UUID>","content_ref":"demo"}'
```

Response includes `batch_id` and expanded `commands` sent to all connected nodes.

## Handoff (app WebSocket)

Connect to `ws://localhost:8000/ws/app` with either:

**Headers (devices / non-browser):**

- `Authorization: Bearer <control_token>`
- `X-TV-Stretch-Home: <home_uuid>`

**Query parameters (browser):** WebSockets in the browser cannot set custom headers. Use:

- `?home_id=<home_uuid>&token=<control_token>`

Hosted demo UI: open `http://localhost:8000/ui/` after starting the API.

Send:

```json
{"v":1,"type":"presence","active_room_id":"<ROOM_UUID>","content_ref":"optional"}
```

Server applies session state, logs an event, broadcasts a **`command_batch`** to devices, and replies:

```json
{"v":1,"type":"handoff_applied","batch_id":"..."}
```

## Device WebSocket protocol

Devices connect to `ws://host/ws/device` with node `api_key` and home id headers.

- **hello**: `{"v":1,"type":"hello","node":{"room_id":"...","home_id":"...","fw":"0.2.0"}}`
- **heartbeat**: periodic `{"v":1,"type":"heartbeat"}`
- **command_batch**: from server; firmware executes commands and sends **ack**: `{"v":1,"type":"ack","batch_id":"...","ok":true}`

## Diagnostics

- `GET /diagnostics/overview` — counts + WebSocket snapshot
- `GET /diagnostics/homes/{home_id}/live` — connected node sockets for that home
- `GET /health/ready` — DB reachability smoke check

## OTA (firmware hosting)

- `GET /ota/manifest` — JSON `version` + `url` (or `url: null` if no file configured)
- `GET /ota/firmware.bin` — binary when `TV_STRETCH_OTA_FIRMWARE_PATH` points to a file on disk

Set `TV_STRETCH_PUBLIC_BASE_URL` so manifest URLs are reachable from the device LAN (e.g. `http://192.168.1.10:8000`).

## Events

- `GET /sessions/{home_id}/events?limit=50` — recent `EventLog` rows (handoffs, device acks)
