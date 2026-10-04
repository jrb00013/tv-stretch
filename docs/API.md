# HTTP and WebSocket API

Base URL: `http://localhost:8000` (or your host). OpenAPI UI: `/docs`. Root `/` redirects to `/ui/` (browser lab).

## Authentication model

- **Nodes** (TV hardware): `Authorization: Bearer <node_api_key>` and `X-TV-Stretch-Home: <home_uuid>` on **`/ws/device`**.  
  For **browser testing** (no custom headers), the same credentials may be passed as query parameters:  
  `ws://host/ws/device?home_id=<uuid>&token=<api_key>` (or `api_key=` instead of `token=`).

- **Apps** (phone / automation): `X-Control-Token: <home.control_token>` on REST routes under `/homes`, `/rooms`, `/nodes`, `/sessions`, `/spatial`, `/presence`, etc.

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
- `GET /health/ready` — DB reachability smoke check. JSON includes `version` and `presence_handoff_min_confidence` (same default as `TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE`, for UI / rig tuning).

## OTA (firmware hosting)

- `GET /ota/manifest` — JSON `version` + `url` (or `url: null` if no file configured).
- `GET /ota/firmware.bin` — binary when `TV_STRETCH_OTA_FIRMWARE_PATH` points to a file on disk.

Set `TV_STRETCH_PUBLIC_BASE_URL` so manifest URLs are reachable from the device LAN (e.g. `http://192.168.1.10:8000`).

## Events

- `GET /sessions/events?limit=50` — recent `EventLog` rows (handoffs, device acks, device events, `occupancy_below_threshold`). Requires `X-Control-Token`.

## Idempotency keys

`POST /sessions/handoff`, `/sessions/power`, `/sessions/cec-key` and `/sessions/input-select`
accept an optional `Idempotency-Key` header (≤128 chars). A retry of the same request with the
same key returns the **original** response — same `batch_id`, same commands — and does not
push a second `command_batch` to the TVs or write a second event.

```bash
curl -sS -X POST http://localhost:8000/sessions/handoff \
  -H 'Content-Type: application/json' \
  -H "X-Control-Token: <CONTROL_TOKEN>" \
  -H 'Idempotency-Key: 9f2c-handoff-1' \
  -d '{"active_room_id":"<ROOM_UUID>"}'
```

Responses:

| Situation | Result |
|---|---|
| First use of the key | Normal response, no replay header |
| Same key, same payload, already completed | Stored response + `Idempotent-Replay: true` |
| Same key, **different** payload | `409` `Idempotency-Key was already used for a different request payload` |
| Same key, original request still in flight | `409` `a request with this Idempotency-Key is still in flight` |
| Key longer than 128 chars or blank | `400` |

Details:

- Keys are scoped **per home**; two homes may use the same key independently.
- The fingerprint covers the endpoint plus the body **with defaults resolved**
  (`{"active_room_id": …, "content_ref": null, "standby_others": true}`), so `{}` and an
  explicit `"standby_others": true` are the same request.
- Records live for 24 h, then the key is reusable. They are stored in the `idempotencyrecord`
  table (created automatically) and removed with the home.
- Omitting the header keeps the previous behaviour: every call executes.

## Command batch delivery

Every `command_batch` the server pushes is tracked until the connected nodes ack it.
Batches are **not** persisted (in-memory only, lost on restart), so lifecycle
transitions are also written to the event log as `command_batch_retry`.

- `GET /sessions/batches` — in-flight, dead-lettered and recently completed batches for the home.
- `GET /sessions/batches/{batch_id}` — one batch, or `404` when unknown / owned by another home.

```json
{
  "batch_id": "0f0c…",
  "status": "pending | retry | complete | failed",
  "attempts": 1,
  "max_attempts": 3,
  "expected_nodes": ["6b1e…", "9f42…"],
  "acked_nodes": ["6b1e…"],
  "failed_nodes": [],
  "next_attempt_at": "2026-06-09T21:10:04+00:00",
  "last_error": null
}
```

Semantics:

- `expected_nodes` is the set of nodes connected **at push time**. A batch completes when
  every expected node has acked; the first `ok: true` ack settles it when no node was connected.
- A batch with unacked nodes is redelivered with exponential backoff (2s, 4s) up to
  `max_attempts`, including batches pushed while every node was offline — a node that
  reconnects inside the window still receives them.
- `ok: false` acks (or an exhausted attempt budget) mark the batch `failed`; it stays readable
  in the dead-letter store. Dead letters and completed batches are bounded (200 / 100).

Device acks carry the same payload as before; `error` is optional:

```json
{"type":"ack","batch_id":"0f0c…","ok":false,"error":"cec timeout"}
```

## Spatial maps (SLAM / floor-plan JSON)

Authenticates with `X-Control-Token` (same as other home APIs).

- `POST /spatial/maps` — body: `{ "label": "floor1", "schema_version": "slam.v1", "payload": { ... } }`. Upserts by **label** per home.
- `GET /spatial/maps` — list map summaries (no large payload).
- `GET /spatial/maps/{map_id}` — full map including `payload`.
- `DELETE /spatial/maps/{map_id}`

## Presence / occupancy (optical SLAM → TV handoff)

- `POST /presence/occupancy` — body:

```json
{
  "room_id": "<ROOM_UUID>",
  "confidence": 0.85,
  "source": "optical_slam",
  "map_id": null,
  "pose": { "x": 0, "y": 0, "yaw": 0 },
  "content_ref": null,
  "standby_others": true
}
```

If `confidence` is **below** `TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE` (default `0.65`, overridable via env), the server **does not** hand off; response includes `"handoff": false, "reason": "below_threshold"`.

If the user is **already** in the active room, returns `"handoff": false, "reason": "already_active"`.

Otherwise runs the same coordinator path as `POST /sessions/handoff` and pushes `command_batch` to nodes.
