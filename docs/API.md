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

## Metrics

`GET /metrics` — Prometheus text exposition format (`text/plain; version=0.0.4`).
Unauthenticated, like `/health` and `/diagnostics/overview`: expose it on an internal
interface or behind the reverse proxy, not on the open internet.

| Series | Type | Labels |
|---|---|---|
| `tv_stretch_http_requests_total` | counter | `method`, `path`, `status` |
| `tv_stretch_http_request_duration_seconds` | histogram | `path` |
| `tv_stretch_build_info` | gauge | `version` |
| `tv_stretch_ws_connections` | gauge | `type` = `device` \| `app` |
| `tv_stretch_command_batches` | gauge | `status` = `pending` \| `completed` \| `dead_letter` |
| `tv_stretch_nodes` | gauge | `status` = `online` \| `stale` \| `offline` \| `unknown` |
| `tv_stretch_homes` | gauge | — |

- `path` is the **route template** (`/rooms/{room_id}`), never the raw path. Labelling per
  UUID would blow up cardinality and take the scrape down with it; unmatched requests share a
  single `unmatched` bucket.
- No metric carries a `home_id` label — per-home series would multiply cardinality again. Use
  the authenticated per-home routes (`/sessions/health`, `/ota/rollout`, …) for that.
- Counters and histograms are in-process and reset on restart. Gauges (connections, batch
  depth, node health) are computed live at scrape time, so they are correct immediately after
  a restart.
- Every response also carries `X-Response-Time-Ms`.

Scrape config sketch:

```yaml
scrape_configs:
  - job_name: tv-stretch
    static_configs:
      - targets: ["192.168.1.10:8000"]
```

## OTA (firmware hosting)

- `GET /ota/manifest` — JSON `version` + `url` + `available` (`url: null` when no file is configured).
- `GET /ota/firmware.bin` — binary when `TV_STRETCH_OTA_FIRMWARE_PATH` points to a file on disk.
- `GET /ota/rollout` — **authenticated** per-node firmware status for the home (exposes node ids).
- `PUT /ota/rollout` — set the `target_version` every node should run (1–32 chars).
- `DELETE /ota/rollout` — stop tracking (`404` if none).

Set `TV_STRETCH_PUBLIC_BASE_URL` so manifest URLs are reachable from the device LAN (e.g. `http://192.168.1.10:8000`).

Nodes report `firmware_version` in their `hello` message; the rollout compares it to the target:

```json
{
  "target_version": "0.7.0",
  "manifest_version": "0.7.0",
  "manifest_matches_target": true,
  "nodes": [{"node_id": "…", "name": "living-tv", "firmware_version": "0.6.9", "status": "behind"}],
  "summary": {"total": 1, "converged": 0, "pending": 1, "ahead": 0, "unknown": 0}
}
```

| `status` | Meaning |
|---|---|
| `up_to_date` | Reported version equals the target |
| `behind` | Reported version sorts lower than the target |
| `ahead` | Reported version sorts **higher** (e.g. after rolling back a target) |
| `unknown` | No target set, the node has never reported a version, or the version has no numeric content |

- Versions compare **numerically**, not as strings: `0.10.0` is newer than `0.7.0`.
  Build metadata after `+` is ignored, so `0.9.0+build7` is still `0.9.0`.
- `manifest_matches_target: false` means the server is not serving the version you asked to
  roll out — nodes can never converge until `TV_STRETCH_OTA_FIRMWARE_VERSION` and the hosted
  binary match. It is reported rather than left for someone to debug from a stuck rollout.
- Nothing is pushed by these routes; devices pull from `/ota/manifest` on their own schedule.

## Events

`GET /sessions/events` returns recent `EventLog` rows (handoffs, device acks, device events,
`occupancy_below_threshold`, `handoff_suppressed`, `standby_all`, …). Requires `X-Control-Token`.

| Param | Meaning |
|---|---|
| `limit` | 1–500, default 50 |
| `kind` | Exact event kind (see `GET /sessions/events/kinds`) |
| `since` | ISO-8601; only events at or after this instant |
| `until` | ISO-8601; only events strictly before this instant |
| `cursor` | Keyset cursor from `X-Next-Cursor`; continues strictly before that event |

```bash
curl -sS "http://localhost:8000/sessions/events?kind=handoff&since=2026-06-09T00:00:00Z&limit=100" \
  -H "X-Control-Token: <CONTROL_TOKEN>"
```

- Timestamps **without** a timezone are read as UTC. Prefer the `Z` form — a raw `+00:00` in a
  query string decodes to a space.
- Pagination is keyset-based, so walking with `cursor` stays stable while new events arrive.
  `X-Next-Cursor` is only present when a full page was returned, and is emitted as
  `…Z` so it can be pasted straight into `?cursor=`.
- `since` after `until` → `422`.

Retention — `DELETE /sessions/events` returns `204` and `X-Deleted-Count`:

| Call | Effect |
|---|---|
| `DELETE /sessions/events` | Clear the whole log (previous behaviour) |
| `DELETE /sessions/events?older_than_seconds=3600` | Prune rows older than an age |
| `DELETE /sessions/events?before=<ISO-8601>` | Prune rows before an instant |
| both | The **stricter** (older) cutoff wins |

Rows for other homes are never touched. There is no automatic retention job yet — schedule
the prune yourself or call it from cron.

## Content library + now playing

`content_ref` has always been a free-form string on a handoff. The library gives those refs
titles, sources and play history, so "what is playing?" is answerable and the house has some
sense of what gets watched. Requires `X-Control-Token`.

| Route | Purpose |
|---|---|
| `POST /content` | Register an entry (`201`); duplicate `ref` in the same home → `409` |
| `GET /content` | List, newest first; filter with `?kind=` and/or `?ref=` |
| `GET /content/top?limit=5` | Most-played entries (never-played excluded, limit clamped 1–50) |
| `GET /content/{content_id}` | One entry |
| `PATCH /content/{content_id}` | Partial update, including `metadata` |
| `DELETE /content/{content_id}` | Remove; the `ref` becomes reusable |
| `GET /sessions/now-playing` | Active room + resolved catalogue entry |

```bash
curl -sS -X POST http://localhost:8000/content \
  -H 'Content-Type: application/json' \
  -H "X-Control-Token: <CONTROL_TOKEN>" \
  -d '{"ref":"netflix:stranger-things-s4","title":"Stranger Things S4",
       "source":"app:netflix","kind":"tv","duration_seconds":3600,
       "metadata":{"season":4,"episode":1}}'
```

- `ref` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` — it travels in URLs and command
  payloads. It is unique per home, so two homes may use the same ref.
- **Handoffs count plays.** Every handoff whose `content_ref` matches an entry increments
  `play_count` and stamps `last_played_at`, on all three handoff paths (REST, occupancy, app
  WebSocket). The `handoff` event payload gains `content_title`.
- **Registration is never required.** An unregistered `content_ref` still works everywhere;
  `now-playing` just reports `content: null` for it. Clients must not have to pre-register
  content to move a TV.
- `now-playing` returns `{home_id, active_room_id, content_ref, content, playing_since}`;
  with no active room it returns `active_room_id: null`.

## Presence hysteresis (dwell + vacancy release)

One above-threshold reading is not evidence that somebody settled in — SLAM noise, someone
crossing the doorway, or a pet all produce one, and each switches the TV. Two opt-in
hysteresis controls sit in front of the occupancy handoff:

| Env var | Default | Effect |
|---|---|---|
| `TV_STRETCH_PRESENCE_DWELL_SECONDS` | `0` (off) | Continuous above-threshold occupancy required before a handoff fires |
| `TV_STRETCH_PRESENCE_DWELL_MAX_GAP_SECONDS` | `30` | A reporting gap longer than this restarts the dwell timer |
| `TV_STRETCH_PRESENCE_RELEASE_SECONDS` | `0` (off) | Sustained below-threshold reporting in the **active** room before the TVs stand by |

Defaults are `0` so existing behaviour is unchanged: enable them per deployment.

Dwell semantics:

- The clock starts at the first qualifying reading for a room and only advances while readings
  for **that same room** keep arriving.
- Switching target room, or a gap longer than `*_MAX_GAP_SECONDS`, restarts it.
- While waiting, `POST /presence/occupancy` returns `200` with `handoff: false`,
  `reason: "dwell"` and `dwell_remaining_seconds`. Readings are still stored; session state,
  events and command batches are untouched.
- Order of checks: threshold → quiet hours → already-active → dwell → handoff.

Vacancy release:

- Driven by the **existing** below-threshold path — no new endpoint, no new client behaviour.
  A sensor that keeps reporting the active room as empty eventually gets a `standby_all`
  command batch, and session state is cleared (`active_room_id: null`, `content_ref: null`).
- The first low reading starts the clock, so a release always needs at least two observations.
- Vacancy reported for a room that is *not* the active room never releases anything.
- Release events use kind `standby_all`; the presence release also publishes MQTT
  `standby_all` with `source: presence_release`.

- `GET /presence/hysteresis` — current candidate (`room_id`, `reports`, `confidence`,
  `first_seen_at`), `vacant_since` and the effective timings. Requires `X-Control-Token`.
- Tracker state is in-memory per home, so a restart clears a pending dwell.

## Quiet hours (do-not-disturb)

A per-home window that suppresses **automatic** TV handoffs — nobody wants the living-room TV
waking up because a presence sensor noticed movement at 03:00. Requires `X-Control-Token`.

- `GET /quiet-hours` — the stored window plus `active_now`, `minutes_remaining`, `next_transition`.
- `PUT /quiet-hours` — create or replace. `start_minute`/`end_minute` are minutes from midnight
  **UTC** (0–1439) and must differ; `weekdays` is ISO weekday numbers (`1`=Mon … `7`=Sun).
- `DELETE /quiet-hours` — remove the window.

```json
{"enabled": true, "start_minute": 1320, "end_minute": 420, "weekdays": "1,2,3,4,5,6,7"}
```

Behaviour:

| Path | During the window |
|---|---|
| `POST /sessions/handoff` | `200` with `ok: false`, `suppressed: true`, `reason: "quiet_hours"`, `batch_id: null`, no commands pushed |
| `POST /presence/occupancy` | Reading is still stored; `handoff: false`, `reason: "quiet_hours"` |
| `/ws/app` `presence` | Reply `{"v":1,"type":"handoff_suppressed","reason":"quiet_hours","minutes_remaining":N}` |

- **Override**: send `"override_quiet_hours": true` on the REST handoff (or `override_quiet_hours`
  in the app WebSocket message) when a *person* explicitly asks for a TV. Sensor-driven presence
  cannot override — it has no field for it.
- Every suppression writes a `handoff_suppressed` event with the room, source and minutes
  remaining, so "why didn't the TV turn on?" is answerable from `/sessions/events`.
- Suppressed handoffs still consume an `Idempotency-Key` and replay the suppression, not a
  later success.
- **Weekday semantics for windows that wrap midnight**: the list applies to the day the window
  *starts*, so `"weekdays": "1,2,3,4,5"` with `22:00→07:00` means quiet Monday through Friday
  night, waking up Saturday morning — not quiet again on Saturday night.
- Times are UTC. There is no per-home timezone yet; if you need local quiet hours, convert
  before writing the window.

## Per-room AV policy

Each room can carry an AV policy applied on **every** handoff into it (e.g. a kids' room
that always starts muted and capped, or a bedroom TV that must never take over the house).
Requires `X-Control-Token`; all three routes are home-scoped (`404` for another home's room).

- `GET /rooms/{room_id}/policy` — stored policy, or defaults with `updated_at: null`.
- `PUT /rooms/{room_id}/policy` — create or replace. `preferred_input` requires `input_physical_address`.
- `DELETE /rooms/{room_id}/policy` — fall back to coordinator defaults.

```json
{
  "volume_cap": 45,
  "mute_on_handoff": true,
  "preferred_input": "shield-hdmi1",
  "input_physical_address": 8192,
  "standby_on_inactive": true
}
```

Emitted commands (in order, before the room is switched active):

| Field | Command | Notes |
|---|---|---|
| `preferred_input` + `input_physical_address` | `cec_set_stream_path` | Address is a CEC physical address (`0x0000`–`0xFFFF`), not a name |
| `volume_cap` (0–100) | `cec_send_raw` → `SET_AUDIO_VOLUME` (0x41) | Mapped to 16 CEC steps, always rounding **down**, so the TV never gets louder than the cap; `0` is CEC mute |
| `mute_on_handoff` | `cec_user_control` with key `0x41` | CEC MUTE |
| `standby_on_inactive: false` | suppresses the `policy` standby step | Effective standby is `standby_others AND standby_on_inactive` |

Only command types the node firmware dispatches are emitted. The ceiling is a starting
point, not a limiter — someone can still turn the volume up with the remote afterwards.

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
