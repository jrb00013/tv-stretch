from __future__ import annotations

import secrets
import uuid
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, select

from app.db import get_session
from app.models import WebhookEndpoint
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import webhooks as wh

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = structlog.get_logger(__name__)


class WebhookCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://homeassistant.local/api/tv-stretch",
                "events": ["handoff", "power"],
            }
        }
    )

    url: str = Field(max_length=512)
    #: Event names to subscribe to; empty/omitted means every event.
    events: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v.strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must use http or https")
        if not parsed.netloc:
            raise ValueError("url must include a host")
        return v.strip()

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        unknown = [e for e in v if e not in wh.KNOWN_EVENTS]
        if unknown:
            raise ValueError(f"unknown events: {', '.join(sorted(unknown))}")
        return sorted(set(v))


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=512)
    events: list[str] | None = None
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return WebhookCreate.validate_url(v)

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return WebhookCreate.validate_events(v)


class WebhookRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    url: str
    events: list[str]
    enabled: bool
    last_delivery_at: str | None = None
    last_status: int | None = None
    last_error: str | None = None
    failure_count: int
    success_count: int
    created_at: str


class WebhookCreated(WebhookRead):
    #: Returned once, on create and on rotate only.
    secret: str


def _to_read(endpoint: WebhookEndpoint) -> WebhookRead:
    return WebhookRead(
        id=endpoint.id,
        home_id=endpoint.home_id,
        url=endpoint.url,
        events=wh.parse_events(endpoint.events),
        enabled=endpoint.enabled,
        last_delivery_at=(
            endpoint.last_delivery_at.isoformat() if endpoint.last_delivery_at else None
        ),
        last_status=endpoint.last_status,
        last_error=endpoint.last_error,
        failure_count=endpoint.failure_count,
        success_count=endpoint.success_count,
        created_at=endpoint.created_at.isoformat(),
    )


def _require(session: Session, auth: AuthenticatedHome, webhook_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = session.get(WebhookEndpoint, webhook_id)
    if endpoint is None or endpoint.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="webhook not found")
    return endpoint


@router.post("", response_model=WebhookCreated, status_code=201)
@limiter.limit("10/minute")
def create_webhook(
    request: Request,
    body: WebhookCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> WebhookCreated:
    """Register an endpoint. The signing secret is shown once and never again."""
    endpoint = WebhookEndpoint(
        home_id=auth.home.id,
        url=body.url,
        secret=secrets.token_urlsafe(32),
        events=",".join(body.events),
        enabled=body.enabled,
    )
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    logger.info("webhook_created", home_id=str(auth.home.id), events=body.events)
    return WebhookCreated(**_to_read(endpoint).model_dump(), secret=endpoint.secret)


@router.get("", response_model=list[WebhookRead])
def list_webhooks(
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> list[WebhookRead]:
    rows = session.exec(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.home_id == auth.home.id)
        .order_by(WebhookEndpoint.created_at)  # type: ignore[arg-type]
    ).all()
    return [_to_read(r) for r in rows]


@router.get("/{webhook_id}", response_model=WebhookRead)
def get_webhook(
    webhook_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> WebhookRead:
    return _to_read(_require(session, auth, webhook_id))


@router.patch("/{webhook_id}", response_model=WebhookRead)
@limiter.limit("10/minute")
def update_webhook(
    request: Request,
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> WebhookRead:
    endpoint = _require(session, auth, webhook_id)
    data = body.model_dump(exclude_unset=True)
    if "url" in data and data["url"] is not None:
        endpoint.url = data["url"]
    if "events" in data and data["events"] is not None:
        endpoint.events = ",".join(data["events"])
    if "enabled" in data and data["enabled"] is not None:
        endpoint.enabled = data["enabled"]
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    return _to_read(endpoint)


@router.delete("/{webhook_id}", status_code=204)
@limiter.limit("10/minute")
def delete_webhook(
    request: Request,
    webhook_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> None:
    session.delete(_require(session, auth, webhook_id))
    session.commit()


class SecretRotated(BaseModel):
    webhook_id: uuid.UUID
    secret: str


@router.post("/{webhook_id}/rotate-secret", response_model=SecretRotated)
@limiter.limit("5/minute")
def rotate_secret(
    request: Request,
    webhook_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> SecretRotated:
    """Issue a new signing secret, invalidating signatures from the old one."""
    endpoint = _require(session, auth, webhook_id)
    endpoint.secret = secrets.token_urlsafe(32)
    session.add(endpoint)
    session.commit()
    logger.info("webhook_secret_rotated", webhook_id=str(webhook_id))
    return SecretRotated(webhook_id=webhook_id, secret=endpoint.secret)


class TestDelivery(BaseModel):
    ok: bool
    status: int | None = None
    error: str | None = None
    attempts: int = 0


@router.post("/{webhook_id}/test", response_model=TestDelivery)
@limiter.limit("10/minute")
async def test_webhook(
    request: Request,
    webhook_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> TestDelivery:
    """Send a signed ``test`` delivery so a receiver can be verified before it matters."""
    endpoint = _require(session, auth, webhook_id)
    results = await wh.get_dispatcher().deliver(
        session, endpoint, "test", {"webhook_id": str(webhook_id)}
    )
    result = results[0]
    return TestDelivery(
        ok=result.ok, status=result.status, error=result.error, attempts=result.attempts
    )
