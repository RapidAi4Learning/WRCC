"""Content item lifecycle state machine (HITL workflow, plan §5).

One source of truth for which status transitions are legal. The service layer
calls ``assert_transition`` before mutating an item so an illegal move surfaces
as a clean 409 rather than silent corruption.

    draft → pending_approval → approved
              │        │
              │        └→ rejected → draft (edit)
              └→ draft (edit)
    any live state → archived; archived → draft (restore, fresh review cycle)
"""

from __future__ import annotations

from app.db.enums import ContentStatus as S

_ALLOWED: dict[S, set[S]] = {
    S.draft: {S.pending_approval, S.archived},
    S.pending_approval: {S.approved, S.rejected, S.draft, S.archived},
    S.rejected: {S.draft, S.archived},
    S.approved: {S.archived},
    S.archived: {S.draft},
}


class ContentTransitionError(ValueError):
    """Raised when a status transition is not permitted by the state machine."""


def assert_transition(current: S, target: S) -> None:
    if target not in _ALLOWED.get(current, set()):
        raise ContentTransitionError(
            f"Cannot move content from '{current.value}' to '{target.value}'."
        )
