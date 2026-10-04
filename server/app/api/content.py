from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import ContentItem, utcnow
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import content as content_service

router = APIRouter(prefix="/content", tags=["content"])
logger = structlog.get_logger(__name__)

#: ``content_ref`` travels in URLs and command payloads, so keep it boring.
REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class ContentCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ref": "netflix:stranger-things-s4",
                "title": "Stranger Things S4",
                "source": "app:netflix",
                "kind": "tv",
                "duration_seconds": 3600,
                "metadata": {"season": 4, "episode": 1},
            }
        }
    )

    ref: str = Field(pattern=REF_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(default="app:unknown", max_length=64)
    kind: str = Field(default="unknown", max_length=32)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    metadata: dict | None = None


class ContentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=64)
    kind: str | None = Field(default=None, max_length=32)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    metadata: dict | None = None


class ContentRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    ref: str
    title: str
    source: str
    kind: str
    duration_seconds: int | None = None
    play_count: int
    last_played_at: str | None = None
    metadata: dict | None = None
    created_at: str
    updated_at: str


def _to_read(item: ContentItem) -> ContentRead:
    metadata = None
    if item.metadata_json:
        try:
            metadata = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            metadata = None
    return ContentRead(
        id=item.id,
        home_id=item.home_id,
        ref=item.ref,
        title=item.title,
        source=item.source,
        kind=item.kind,
        duration_seconds=item.duration_seconds,
        play_count=item.play_count,
        last_played_at=item.last_played_at.isoformat() if item.last_played_at else None,
        metadata=metadata,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


def _require_item(session: Session, auth: AuthenticatedHome, content_id: uuid.UUID) -> ContentItem:
    item = session.get(ContentItem, content_id)
    if item is None or item.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="content not found")
    return item


@router.post("", response_model=ContentRead, status_code=201)
@limiter.limit("30/minute")
def create_content(
    request: Request,
    body: ContentCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> ContentRead:
    """Register a catalogue entry for a ``content_ref``."""
    if content_service.find_by_ref(session, auth.home.id, body.ref) is not None:
        raise HTTPException(status_code=409, detail="content ref already exists for this home")
    item = ContentItem(
        home_id=auth.home.id,
        ref=body.ref,
        title=body.title,
        source=body.source,
        kind=body.kind,
        duration_seconds=body.duration_seconds,
        metadata_json=json.dumps(body.metadata) if body.metadata is not None else None,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    logger.info("content_created", home_id=str(auth.home.id), ref=item.ref)
    return _to_read(item)


@router.get("", response_model=list[ContentRead])
def list_content(
    kind: str | None = None,
    ref: str | None = None,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> list[ContentRead]:
    """List catalogue entries, newest first. Filter by ``kind`` and/or exact ``ref``."""
    stmt = select(ContentItem).where(ContentItem.home_id == auth.home.id)
    if kind:
        stmt = stmt.where(ContentItem.kind == kind)
    if ref:
        stmt = stmt.where(ContentItem.ref == ref)
    stmt = stmt.order_by(ContentItem.created_at.desc())  # type: ignore[arg-type]
    return [_to_read(i) for i in session.exec(stmt).all()]


@router.get("/top", response_model=list[ContentRead])
def top_content(
    limit: int = 5,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> list[ContentRead]:
    """Most-played entries for the home (never-played items excluded)."""
    bounded = max(1, min(limit, 50))
    return [_to_read(i) for i in content_service.most_played(session, auth.home.id, bounded)]


@router.get("/{content_id}", response_model=ContentRead)
def get_content(
    content_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> ContentRead:
    return _to_read(_require_item(session, auth, content_id))


@router.patch("/{content_id}", response_model=ContentRead)
@limiter.limit("30/minute")
def update_content(
    request: Request,
    content_id: uuid.UUID,
    body: ContentUpdate,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> ContentRead:
    item = _require_item(session, auth, content_id)
    data = body.model_dump(exclude_unset=True)
    if "metadata" in data:
        item.metadata_json = json.dumps(data.pop("metadata"))
    for field, value in data.items():
        setattr(item, field, value)
    item.updated_at = utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _to_read(item)


@router.delete("/{content_id}", status_code=204)
@limiter.limit("30/minute")
def delete_content(
    request: Request,
    content_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> None:
    _require_item(session, auth, content_id)
    session.delete(session.get(ContentItem, content_id))  # type: ignore[arg-type]
    session.commit()
