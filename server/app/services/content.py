from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.models import ContentItem, utcnow


def find_by_ref(session: Session, home_id: uuid.UUID, ref: str) -> ContentItem | None:
    return session.exec(
        select(ContentItem).where(ContentItem.home_id == home_id, ContentItem.ref == ref)
    ).first()


def record_play(
    session: Session,
    home_id: uuid.UUID,
    ref: str | None,
) -> ContentItem | None:
    """Count a play of ``ref`` and stamp ``last_played_at``.

    Called from the coordinator so every handoff path (REST, occupancy, app
    WebSocket) keeps play stats in step. Unknown refs are ignored: ``content_ref``
    stays free-form and a client must not have to pre-register content.
    """
    if not ref:
        return None
    item = find_by_ref(session, home_id, ref)
    if item is None:
        return None
    item.play_count += 1
    item.last_played_at = utcnow()
    session.add(item)
    return item


def most_played(session: Session, home_id: uuid.UUID, limit: int = 5) -> list[ContentItem]:
    return list(
        session.exec(
            select(ContentItem)
            .where(ContentItem.home_id == home_id, ContentItem.play_count > 0)
            .order_by(ContentItem.play_count.desc())  # type: ignore[arg-type]
            .limit(limit)
        ).all()
    )
