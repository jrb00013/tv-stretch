from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(prefix="/ota", tags=["ota"])


@router.get("/manifest")
def ota_manifest() -> dict:
    base = settings.public_base_url.rstrip("/")
    path = settings.ota_firmware_path.strip()
    if not path or not Path(path).is_file():
        return {
            "version": settings.ota_firmware_version,
            "url": None,
            "note": "Set TV_STRETCH_OTA_FIRMWARE_PATH to a built tv-stretch-node.bin",
        }
    return {
        "version": settings.ota_firmware_version,
        "url": f"{base}/ota/firmware.bin",
    }


@router.get("/firmware.bin")
def ota_firmware_bin() -> FileResponse:
    path = settings.ota_firmware_path.strip()
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="firmware binary not configured on server")
    return FileResponse(path, media_type="application/octet-stream", filename="tv-stretch-node.bin")
