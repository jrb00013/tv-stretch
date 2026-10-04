from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.services.metrics import (
    CONTENT_TYPE,
    DEFAULT_BUCKETS,
    Histogram,
    MetricsRegistry,
    get_registry,
)


def _series(text: str, name: str) -> list[str]:
    return [
        line for line in text.splitlines() if line.startswith(name) and not line.startswith("#")
    ]


@pytest.fixture(name="registry")
def registry_fixture() -> MetricsRegistry:
    return MetricsRegistry()


def test_counter_accumulates(registry: MetricsRegistry) -> None:
    registry.increment("hits_total", (("route", "/rooms"),))
    registry.increment("hits_total", (("route", "/rooms"),))
    registry.increment("hits_total", (("route", "/health"),))
    assert registry.counter_value("hits_total", (("route", "/rooms"),)) == 2
    assert 'hits_total{route="/rooms"} 2' in registry.render()


def test_gauge_overwrites_rather_than_accumulates(registry: MetricsRegistry) -> None:
    registry.set_gauge("ws_connections", 5, (("type", "device"),))
    registry.set_gauge("ws_connections", 2, (("type", "device"),))
    assert registry.render().count('ws_connections{type="device"} 2') == 1


def test_labels_are_escaped(registry: MetricsRegistry) -> None:
    registry.increment("x_total", (("path", 'a"b\\c'),))
    text = registry.render()
    assert 'x_total{path="a\\"b\\\\c"} 1' in text


def test_help_and_type_headers(registry: MetricsRegistry) -> None:
    registry.describe("hits_total", "How many hits")
    registry.increment("hits_total")
    text = registry.render()
    assert "# HELP hits_total How many hits" in text
    assert "# TYPE hits_total counter" in text


def test_histogram_buckets_are_cumulative(registry: MetricsRegistry) -> None:
    for value in (0.001, 0.02, 0.3, 7.0):
        registry.observe("dur_seconds", value)
    text = registry.render()
    lines = dict(
        (m.group(1), float(m.group(2)))
        for m in re.finditer(r'dur_seconds_bucket\{le="([^"]+)"\} (\d+)', text)
    )
    assert lines["0.005"] == 1
    assert lines["0.025"] == 2
    assert lines["0.5"] == 3
    assert lines["+Inf"] == 4
    assert "dur_seconds_count 4" in text
    assert "dur_seconds_sum 7.321" in text
    counts = [lines[str(b)] if str(b) in lines else lines[_fmt(b)] for b in DEFAULT_BUCKETS]
    assert counts == sorted(counts)


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


def test_histogram_type_header(registry: MetricsRegistry) -> None:
    registry.observe("dur_seconds", 0.1)
    assert "# TYPE dur_seconds histogram" in registry.render()


def test_empty_registry_renders_just_a_newline(registry: MetricsRegistry) -> None:
    assert registry.render() == "\n"


def test_reset_clears_series(registry: MetricsRegistry) -> None:
    registry.increment("a_total")
    registry.set_gauge("b", 1)
    registry.observe("c_seconds", 0.1)
    registry.reset()
    assert registry.render() == "\n"


def test_standalone_histogram_object() -> None:
    hist = Histogram(buckets=(1.0, 2.0))
    hist.observe(0.5)
    hist.observe(1.5)
    hist.observe(9.0)
    lines = hist.render("h")
    # le values are rendered without a trailing ".0"; Prometheus parses them as floats.
    assert 'h_bucket{le="1"} 1' in lines
    assert 'h_bucket{le="2"} 2' in lines
    assert 'h_bucket{le="+Inf"} 3' in lines
    assert "h_count 3" in lines


def test_metrics_endpoint_content_type(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in CONTENT_TYPE


def test_metrics_counts_http_requests(client: TestClient) -> None:
    before = get_registry().counter_value(
        "tv_stretch_http_requests_total",
        (("method", "GET"), ("path", "/health"), ("status", "200")),
    )
    client.get("/health")
    client.get("/health")
    after = get_registry().counter_value(
        "tv_stretch_http_requests_total",
        (("method", "GET"), ("path", "/health"), ("status", "200")),
    )
    assert after == before + 2


def test_metrics_labels_use_route_templates_not_raw_paths(client: TestClient) -> None:
    """Per-UUID path labels would explode cardinality."""
    home = client.post("/homes", json={"name": "metrics"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    for name in ("a", "b", "c"):
        client.post("/rooms", json={"name": name}, headers=headers)

    text = client.get("/metrics").text
    room_series = _series(text, "tv_stretch_http_requests_total")
    labelled = [line for line in room_series if 'path="/rooms"' in line]
    assert len(labelled) == 1
    # Every room POST landed on one series rather than one per room name.
    assert labelled[0].endswith(" 3")


def test_unmatched_paths_share_one_bucket(client: TestClient) -> None:
    client.get("/nope-1")
    client.get("/nope-2")
    text = client.get("/metrics").text
    unmatched = [
        line for line in _series(text, "tv_stretch_http_requests_total") if "unmatched" in line
    ]
    assert len(unmatched) == 1


def test_metrics_exposes_build_and_connection_gauges(client: TestClient) -> None:
    client.get("/metrics")
    text = client.get("/metrics").text
    assert "# TYPE tv_stretch_build_info gauge" in text
    assert re.search(r'tv_stretch_build_info\{version="[^"]+"\} 1', text)
    assert "# TYPE tv_stretch_ws_connections gauge" in text
    assert 'tv_stretch_ws_connections{type="device"} 0' in text
    assert 'tv_stretch_ws_connections{type="app"} 0' in text


def test_metrics_counts_connected_devices(client: TestClient) -> None:
    home = client.post("/homes", json={"name": "ws"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()["id"]
    node = client.post(
        "/nodes/register", json={"room_id": room, "name": "n1"}, headers=headers
    ).json()

    with client.websocket_connect(f"/ws/device?home_id={home['id']}&api_key={node['api_key']}"):
        text = client.get("/metrics").text
    assert 'tv_stretch_ws_connections{type="device"} 1' in text
    text = client.get("/metrics").text
    assert 'tv_stretch_ws_connections{type="device"} 0' in text


def test_metrics_reports_command_batch_depth(client: TestClient) -> None:
    home = client.post("/homes", json={"name": "batches"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "r"}, headers=headers).json()["id"]
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)

    text = client.get("/metrics").text
    assert 'tv_stretch_command_batches{status="pending"} 1' in text
    assert 'tv_stretch_command_batches{status="dead_letter"} 0' in text


def test_metrics_reports_node_health(client: TestClient) -> None:
    home = client.post("/homes", json={"name": "health"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "r"}, headers=headers).json()["id"]
    client.post("/nodes/register", json={"room_id": room, "name": "n1"}, headers=headers)

    text = client.get("/metrics").text
    assert 'tv_stretch_nodes{status="unknown"} 1' in text
    assert "tv_stretch_homes 1" in text


def test_metrics_labels_carry_no_home_identifiers(client: TestClient) -> None:
    for name in ("h1", "h2", "h3"):
        client.post("/homes", json={"name": name})
    text = client.get("/metrics").text
    for line in text.splitlines():
        if line.startswith("tv_stretch_"):
            assert "home_id=" not in line, line
