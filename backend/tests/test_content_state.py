"""Content state machine transitions."""

from __future__ import annotations

import pytest

from app.content.state import ContentTransitionError, assert_transition
from app.db.enums import ContentStatus as S


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.draft, S.pending_approval),
        (S.draft, S.archived),
        (S.pending_approval, S.approved),
        (S.pending_approval, S.rejected),
        (S.pending_approval, S.draft),
        (S.rejected, S.draft),
        (S.approved, S.archived),
        (S.archived, S.draft),
    ],
)
def test_allowed_transitions(current: S, target: S) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.draft, S.approved),  # approval requires the pending gate
        (S.draft, S.rejected),
        (S.approved, S.draft),  # an approved post never silently reopens
        (S.approved, S.pending_approval),
        (S.archived, S.approved),
        (S.rejected, S.approved),
    ],
)
def test_forbidden_transitions(current: S, target: S) -> None:
    with pytest.raises(ContentTransitionError):
        assert_transition(current, target)
