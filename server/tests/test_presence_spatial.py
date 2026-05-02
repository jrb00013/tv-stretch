from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_spatial_map_crud(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "map-home"})
    tok = h.json()["control_token"]
    headers = {"X-Control-Token": tok}

    r = client.post(
        "/spatial/maps",
        headers=headers,
        json={
            "label": "floor1",
            "schema_version": "slam.v1",
            "payload": {"rooms": [{"id": "a", "polygon": [[0, 0], [1, 0]]}]},
        },
    )
    assert r.status_code == 200
    mid = r.json()["id"]

    lst = client.get("/spatial/maps", headers=headers)
    assert lst.status_code == 200
    assert len(lst.json()) == 1

    one = client.get(f"/spatial/maps/{mid}", headers=headers)
    assert one.status_code == 200
    assert one.json()["payload"]["rooms"]

    d = client.delete(f"/spatial/maps/{mid}", headers=headers)
    assert d.status_code == 204


def test_occupancy_below_threshold(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "presence_handoff_min_confidence", 0.9)

    h = client.post("/homes", json={"name": "occ"})
    tok = h.json()["control_token"]
    headers = {"X-Control-Token": tok}
    r1 = client.post("/rooms", json={"name": "r1"}, headers=headers)
    room_id = r1.json()["id"]

    oc = client.post(
        "/presence/occupancy",
        headers=headers,
        json={"room_id": room_id, "confidence": 0.2, "source": "test"},
    )
    assert oc.status_code == 200
    body = oc.json()
    assert body["ok"] is True
    assert body["handoff"] is False
    assert body["reason"] == "below_threshold"


def test_occupancy_triggers_handoff(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "presence_handoff_min_confidence", 0.5)

    h = client.post("/homes", json={"name": "occ2"})
    tok = h.json()["control_token"]
    headers = {"X-Control-Token": tok}
    r1 = client.post("/rooms", json={"name": "r1"}, headers=headers)
    r2 = client.post("/rooms", json={"name": "r2"}, headers=headers)
    room_id = r2.json()["id"]

    client.post(
        "/nodes/register",
        headers=headers,
        json={"room_id": r1.json()["id"], "name": "n1"},
    )

    oc = client.post(
        "/presence/occupancy",
        headers=headers,
        json={"room_id": room_id, "confidence": 0.95, "source": "optical"},
    )
    assert oc.status_code == 200
    body = oc.json()
    assert body["handoff"] is True
    assert body["batch_id"]
    assert any(c.get("cmd") == "cec_broadcast_ping" for c in body["commands"])


def test_occupancy_already_active_skips_batch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "presence_handoff_min_confidence", 0.5)

    h = client.post("/homes", json={"name": "occ3"})
    tok = h.json()["control_token"]
    headers = {"X-Control-Token": tok}
    r1 = client.post("/rooms", json={"name": "r1"}, headers=headers)
    rid = r1.json()["id"]

    first = client.post(
        "/presence/occupancy",
        headers=headers,
        json={"room_id": rid, "confidence": 0.99},
    )
    assert first.json()["handoff"] is True

    second = client.post(
        "/presence/occupancy",
        headers=headers,
        json={"room_id": rid, "confidence": 0.99},
    )
    assert second.status_code == 200
    assert second.json()["handoff"] is False
    assert second.json()["reason"] == "already_active"


def test_delete_home_removes_spatial_maps(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "del"})
    tok = h.json()["control_token"]
    hid = h.json()["id"]
    headers = {"X-Control-Token": tok}
    client.post(
        "/spatial/maps",
        headers=headers,
        json={"label": "x", "schema_version": "slam.v1", "payload": {}},
    )
    assert len(client.get("/spatial/maps", headers=headers).json()) == 1

    d = client.delete(f"/homes/{hid}", headers=headers)
    assert d.status_code == 204

    h2 = client.post("/homes", json={"name": "new"})
    tok2 = h2.json()["control_token"]
    assert client.get("/spatial/maps", headers={"X-Control-Token": tok2}).json() == []
