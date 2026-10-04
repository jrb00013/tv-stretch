from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import FirmwareRollout, Node, utcnow

logger = structlog.get_logger(__name__)

STATUS_UP_TO_DATE = "up_to_date"
STATUS_BEHIND = "behind"
STATUS_AHEAD = "ahead"
STATUS_UNKNOWN = "unknown"

_VERSION_PART = re.compile(r"\d+")


def parse_version(version: str | None) -> tuple[int, ...]:
    """Best-effort numeric version tuple: ``0.10.2-rc1`` -> ``(0, 10, 2, 1)``.

    Build metadata after ``+`` is dropped — ``0.9.0+build7`` is still 0.9.0. Numeric
    parts are picked out of whatever the build system stamped rather than raising;
    a version with no digits at all yields an empty tuple, which callers must treat
    as "unknown", never as "matches".
    """
    if not version:
        return ()
    return tuple(int(p) for p in _VERSION_PART.findall(version.split("+", 1)[0]))


def compare_versions(left: str | None, right: str | None) -> int:
    """Return -1/0/1 comparing two versions numerically, padding the shorter side.

    Plain string comparison is wrong here: ``"0.10.0" < "0.7.0"`` lexicographically,
    which would mark every node on 0.7 as already up to date after a 0.10 rollout.
    """
    a = parse_version(left)
    b = parse_version(right)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def classify_node(node: Node, target_version: str | None) -> str:
    """Rollout status of one node relative to the target version.

    A version with no numeric content (``"unknown"``, ``"dev"``) is reported as
    ``unknown`` rather than being padded to zeros and compared equal — that would
    mark a node as converged when it clearly is not.
    """
    if not target_version:
        return STATUS_UNKNOWN
    if not parse_version(node.firmware_version):
        return STATUS_UNKNOWN
    order = compare_versions(node.firmware_version, target_version)
    if order == 0:
        return STATUS_UP_TO_DATE
    return STATUS_BEHIND if order < 0 else STATUS_AHEAD


def get_rollout(session: Session, home_id: uuid.UUID) -> FirmwareRollout | None:
    return session.get(FirmwareRollout, home_id)


def set_rollout(session: Session, home_id: uuid.UUID, target_version: str) -> FirmwareRollout:
    rollout = get_rollout(session, home_id)
    if rollout is None:
        rollout = FirmwareRollout(home_id=home_id, target_version=target_version)
    else:
        rollout.target_version = target_version
        rollout.updated_at = utcnow()
    session.add(rollout)
    session.commit()
    session.refresh(rollout)
    logger.info("firmware_rollout_set", home_id=str(home_id), target=target_version)
    return rollout


def clear_rollout(session: Session, home_id: uuid.UUID) -> bool:
    rollout = get_rollout(session, home_id)
    if rollout is None:
        return False
    session.delete(rollout)
    session.commit()
    return True


def rollout_status(session: Session, home_id: uuid.UUID, manifest_version: str) -> dict[str, Any]:
    """Per-node rollout status plus counts for a home.

    ``manifest_version`` is what ``GET /ota/manifest`` currently serves. When it does
    not match the target, nodes can never converge — that mismatch is surfaced rather
    than left for someone to discover from a stuck rollout.
    """
    rollout = get_rollout(session, home_id)
    target = rollout.target_version if rollout else None
    nodes = list(session.exec(select(Node).where(Node.home_id == home_id)).all())

    counts = {
        STATUS_UP_TO_DATE: 0,
        STATUS_BEHIND: 0,
        STATUS_AHEAD: 0,
        STATUS_UNKNOWN: 0,
    }
    entries = []
    for node in nodes:
        status = classify_node(node, target)
        counts[status] += 1
        entries.append(
            {
                "node_id": str(node.id),
                "room_id": str(node.room_id),
                "name": node.name,
                "firmware_version": node.firmware_version,
                "status": status,
                "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
            }
        )

    return {
        "home_id": str(home_id),
        "target_version": target,
        "manifest_version": manifest_version,
        "manifest_matches_target": bool(target) and target == manifest_version,
        "nodes": entries,
        "summary": {
            "total": len(nodes),
            "converged": counts[STATUS_UP_TO_DATE],
            "pending": counts[STATUS_BEHIND],
            "ahead": counts[STATUS_AHEAD],
            "unknown": counts[STATUS_UNKNOWN],
        },
        "updated_at": rollout.updated_at.isoformat() if rollout else None,
    }
