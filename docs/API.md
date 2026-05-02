# HTTP and WebSocket API

Base URL: `http://localhost:8000` (or your host). OpenAPI UI: `/docs`. Root `/` redirects to `/ui/` (browser lab).

## Authentication model

- **Nodes** (TV hardware): `Authorization: Bearer <node_api_key>` and `X-TV-Stretch-Home: <home_uuid>` on **`/ws/device`**.  
  For **browser testing** (no custom headers), the same credentials may be passed as query parameters:  
  `ws://host/ws/device?home_id=<uuid>&token=<api_key>` (or `api_key=` instead of `token=`).

- **Apps** (phone / automation): `X-Control-Token: <home.control_token>` on REST routes under `/homes`, `/rooms`, `/nodes`, `/sessions`, etc.

- **App WebSocket** `/ws/app`: `Authorization: Bearer <control_token>` + `X-TV-Stretch-Home: <home_uuid>`, **or** query params `?home_id=<uuid>&token=<control_token>` (required for browsers).

REST endpoints for provisioning (`POST /homes`, `POST /bootstrap/...`) are unauthenticated by default (home LAN / dev). Put the API behind a reverse proxy and TLS before exposing to the internet.

## Bootstrap a home

```bash
curl -sS -X POST http://localhost:8000/bootstrap/home-with-rooms \
  -H 'Content-Type: application/json' \
  -d '{"home_name":"loft","room_names":["living","kitchen","bedroom"]}'
```

Save `home.control_token`, `home.id`, and each `rooms[].id`.

## Register a node per TV

Requires the home control token:

```bash
curl -sS -X POST http://localhost:8000/nodes/register \
  -H 'Content-Type: application/json' \
  -H "X-Control-Token: <CONTROL_TOKEN>" \
  -d '{"room_id":"<ROOM_UUID>","name":"living-tv"}'
```

Save `api_key` into firmware NVS (or Kconfig for dev).

## Handoff (REST)

```bash
curl -sS -X POST http://localhost:8000/sessions/handoff \
  -H 'Content-Type: application/json' \
  -H "X-Control-Token: <CONTROL_TOKEN>" \
  -d '{"active_room_id":"<ROOM_UUID>","content_ref":"demo","standby_others":true}'
```

- `standby_others` (default `true`): when true, the coordinator emits a `policy` command for non-active TVs; when `false`, that step is skipped.

Response includes `batch_id` and expanded `commands` pushed to connected nodes.

## Handoff (app WebSocket)

Connect to `ws://localhost:8000/ws/app` with headers or `?home_id=&token=` as above.

Send presence:

```json
{"v":1,"type":"presence","active_room_id":"<ROOM_UUID>","content_ref":"optional","standby_others":true}
```

Optional: query current session state without HTTP:

```json
{"v":1,"type":"get_session"}
```

Server replies:

```json
{"v":1,"type":"session_state","home_id":"...","active_room_id":null,"content_ref":null,"updated_at":null}
```

After a successful presence handoff:

```json
{"v":1,"type":"handoff_applied","batch_id":"..."}
```

Ping:

```json
{"v":1,"type":"ping"}
```

→ `{"v":1,"type":"pong"}`

## Device WebSocket protocol

Devices connect to `ws://host/ws/device` with node `api_key` and home id (headers **or** query params as above).

**Device → server**

| type | Purpose |
|------|---------|
| `hello` | First contact; may include `node.fw`, `node.room_id`, `node.home_id`. Updates `last_seen_at` and firmware version. |
| `heartbeat` | Periodic liveness; updates `last_seen_at`. |
| `ack` | After executing a `command_batch`: `batch_id`, `ok`. Logged as `device_ack`. |
| `event` | Debug / vendor hooks; payload stored in `EventLog` as `device_event`. |

**Server → device**

- `command_batch`: `{ "v":1, "type":"command_batch", "batch_id":"...", "commands":[...] }`

Schema version field: `v` (currently `1`).

## Diagnostics

- `GET /diagnostics/overview` — counts + WebSocket snapshot (connected device nodes per home).
- `GET /diagnostics/homes/{home_id}/live` — connected device sockets for that home.
- `GET /health` — liveness.
- `GET /health/ready` — DB reachability smoke check.

## OTA (firmware hosting)

- `GET /ota/manifest` — JSON `version` + `url` (or `url: null` if no file configured).
- `GET /ota/firmware.bin` — binary when `TV_STRETCH_OTA_FIRMWARE_PATH` points to a file on disk.

Set `TV_STRETCH_PUBLIC_BASE_URL` so manifest URLs are reachable from the device LAN (e.g. `http://192.168.1.10:8000`).

## Events

- `GET /sessions/events?limit=50` — recent `EventLog` rows (handoffs, device acks, device events). Requires `X-Control-Token`.
