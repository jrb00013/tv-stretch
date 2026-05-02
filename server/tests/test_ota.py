from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_manifest_without_firmware(client: TestClient) -> None:
    r = client.get("/ota/manifest")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert body.get("url") is None


def test_firmware_bin_404_when_unset(client: TestClient) -> None:
    r = client.get("/ota/firmware.bin")
    assert r.status_code == 404


def test_firmware_bin_serves_file(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    import app.config as cfg

    bin_path = tmp_path / "fake.bin"
    bin_path.write_bytes(b"ABCD")

    monkeypatch.setattr(cfg.settings, "ota_firmware_path", str(bin_path))
    monkeypatch.setattr(cfg.settings, "ota_firmware_version", "9.9.9")
    monkeypatch.setattr(cfg.settings, "public_base_url", "http://test")

    r = client.get("/ota/firmware.bin")
    assert r.status_code == 200
    assert r.content == b"ABCD"

    m = client.get("/ota/manifest")
    assert m.status_code == 200
    assert m.json()["url"] == "http://test/ota/firmware.bin"
    assert m.json()["version"] == "9.9.9"
