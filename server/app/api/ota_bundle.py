from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(prefix="/ota", tags=["ota"])


def current_manifest() -> dict:
    """Resolve what the server is currently serving to devices.

    Shared by ``GET /ota/manifest`` and the rollout status so both report the same
    version — a rollout target that nothing serves can never converge.
    """
    base = settings.public_base_url.rstrip("/")
    path = settings.ota_firmware_path.strip()
    if not path or not Path(path).is_file():
        return {
            "version": settings.ota_firmware_version,
            "url": None,
            "available": False,
            "note": "Set TV_STRETCH_OTA_FIRMWARE_PATH to a built tv-stretch-node.bin",
        }
    return {
        "version": settings.ota_firmware_version,
        "url": f"{base}/ota/firmware.bin",
        "available": True,
    }


@router.get("/manifest")
def ota_manifest() -> dict:
    return current_manifest()


@router.get("/firmware.bin")
def ota_firmware_bin() -> FileResponse:
    path = settings.ota_firmware_path.strip()
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="firmware binary not configured on server")
    return FileResponse(path, media_type="application/octet-stream", filename="tv-stretch-node.bin")
