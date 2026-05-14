from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import select

from app.models import SpatialMap, utcnow
from app.security.auth import AuthenticatedHome, require_home_auth

router = APIRouter(prefix="/spatial", tags=["spatial"])


class SpatialMapPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "label": "floor1",
                "schema_version": "slam.v1",
                "payload": {
                    "origin": "slam_export",
                    "rooms": [
                        {
                            "id": "living",
                            "polygon_m": [[0, 0], [5.2, 0], [5.2, 4.1], [0, 4.1]],
                        }
                    ],
                },
            }
        }
    )

    label: str = "default"
    schema_version: str = "slam.v1"
    payload: dict

    def validate_payload(self) -> list[str]:
        errors = []
        if "rooms" in self.payload:
            for i, room in enumerate(self.payload["rooms"]):
                if "id" not in room:
                    errors.append(f"room {i}: missing id")
                if "polygon_m" in room:
                    poly = room["polygon_m"]
                    if not isinstance(poly, list) or len(poly) < 3:
                        errors.append(f"room {i}: polygon_m must have at least 3 points")
        return errors


class SpatialMapSummary(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    label: str
    schema_version: str
    updated_at: str


class SpatialMapDetail(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    label: str
    schema_version: str
    payload: dict
    updated_at: str


@router.post("/maps", response_model=SpatialMapSummary)
def create_or_replace_map(
    body: SpatialMapPayload,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SpatialMapSummary:
    """Store SLAM / floor-plan metadata JSON for this home (upsert by label)."""
    errors = body.validate_payload()
    if errors:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {', '.join(errors)}")

    existing = auth.session.exec(
        select(SpatialMap).where(SpatialMap.home_id == auth.home.id, SpatialMap.label == body.label)
    ).first()
    blob = json.dumps(body.payload)
    if existing:
        existing.schema_version = body.schema_version
        existing.payload_json = blob
        existing.updated_at = utcnow()
        auth.session.add(existing)
        auth.session.commit()
        auth.session.refresh(existing)
        m = existing
    else:
        m = SpatialMap(
            home_id=auth.home.id,
            label=body.label,
            schema_version=body.schema_version,
            payload_json=blob,
        )
        auth.session.add(m)
        auth.session.commit()
        auth.session.refresh(m)
    return SpatialMapSummary(
        id=m.id,
        home_id=m.home_id,
        label=m.label,
        schema_version=m.schema_version,
        updated_at=m.updated_at.isoformat(),
    )


@router.get("/maps", response_model=list[SpatialMapSummary])
def list_maps(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[SpatialMapSummary]:
    rows = list(
        auth.session.exec(select(SpatialMap).where(SpatialMap.home_id == auth.home.id)).all()
    )
    return [
        SpatialMapSummary(
            id=r.id,
            home_id=r.home_id,
            label=r.label,
            schema_version=r.schema_version,
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/maps/{map_id}", response_model=SpatialMapDetail)
def get_map(
    map_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SpatialMapDetail:
    r = auth.session.get(SpatialMap, map_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="map not found")
    try:
        payload = json.loads(r.payload_json)
    except json.JSONDecodeError:
        payload = {}
    return SpatialMapDetail(
        id=r.id,
        home_id=r.home_id,
        label=r.label,
        schema_version=r.schema_version,
        payload=payload,
        updated_at=r.updated_at.isoformat(),
    )


@router.delete("/maps/{map_id}", status_code=204)
def delete_map(
    map_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    r = auth.session.get(SpatialMap, map_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="map not found")
    auth.session.delete(r)
    auth.session.commit()
