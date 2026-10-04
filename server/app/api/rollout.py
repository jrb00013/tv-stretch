from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.ota_bundle import current_manifest
from app.db import get_session
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import firmware_rollout as fr

router = APIRouter(prefix="/ota", tags=["ota"])
logger = structlog.get_logger(__name__)


class RolloutBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"target_version": "0.7.0"}})

    target_version: str = Field(min_length=1, max_length=32)


@router.get("/rollout", response_model=dict)
def read_rollout(
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> dict:
    """Per-node firmware status against this home's rollout target.

    Authenticated, unlike ``/ota/manifest``: it exposes node ids and versions.
    """
    return fr.rollout_status(session, auth.home.id, current_manifest()["version"])


@router.put("/rollout", response_model=dict)
@limiter.limit("10/minute")
def put_rollout(
    request: Request,
    body: RolloutBody,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> dict:
    """Set (or change) the firmware version every node should be running."""
    fr.set_rollout(session, auth.home.id, body.target_version.strip())
    status = fr.rollout_status(session, auth.home.id, current_manifest()["version"])
    if not status["manifest_matches_target"]:
        logger.warning(
            "rollout_target_not_served",
            home_id=str(auth.home.id),
            target=status["target_version"],
            manifest=status["manifest_version"],
        )
    return status


@router.delete("/rollout", status_code=204)
@limiter.limit("10/minute")
def delete_rollout(
    request: Request,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> None:
    """Stop tracking a rollout; nodes go back to reporting as ``unknown``."""
    if not fr.clear_rollout(session, auth.home.id):
        raise HTTPException(status_code=404, detail="no rollout for this home")
    logger.info("firmware_rollout_cleared", home_id=str(auth.home.id))
