#!/usr/bin/env bash
# Examples for spatial maps + occupancy handoffs. Set BASE and TOKEN first.
# TOKEN = home control_token from bootstrap or POST /homes.

set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:?export TOKEN=your_control_token}"

echo "=== GET /health/ready (includes presence_handoff_min_confidence) ==="
curl -sS "${BASE}/health/ready" | python3 -m json.tool

echo
echo "=== GET /spatial/maps ==="
curl -sS -H "X-Control-Token: ${TOKEN}" "${BASE}/spatial/maps" | python3 -m json.tool

echo
echo "=== POST /spatial/maps (upsert by label) ==="
curl -sS -X POST "${BASE}/spatial/maps" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: ${TOKEN}" \
  -d '{"label":"floor1","schema_version":"slam.v1","payload":{"rooms":[]}}' | python3 -m json.tool

# Uncomment and set ROOM_ID from GET /rooms:
# ROOM_ID="00000000-0000-4000-8000-000000000001"
# echo
# echo "=== POST /presence/occupancy ==="
# curl -sS -X POST "${BASE}/presence/occupancy" \
#   -H "Content-Type: application/json" \
#   -H "X-Control-Token: ${TOKEN}" \
#   -d "{\"room_id\":\"${ROOM_ID}\",\"confidence\":0.9,\"source\":\"spatial-presence-examples\",\"standby_others\":true}" \
#   | python3 -m json.tool
