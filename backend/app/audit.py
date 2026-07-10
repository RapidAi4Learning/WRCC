"""Shared audit-trail writer.

Every mutation (generation, workflow transition, sync approval) records an
``audit_logs`` row through this one helper so the trail is uniform and no
domain re-implements the write.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


def record_audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    payload_diff: dict | None = None,
) -> None:
    """Stage an audit row on the session (committed by the calling service)."""
    session.add(
        AuditLog(
            user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_diff=payload_diff,
        )
    )
