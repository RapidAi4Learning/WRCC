"""Bounded retry shared by the live publishers.

Only ``rate_limited`` and ``transient`` failures are retried. An auth failure
means the token is dead and retrying just burns quota; an ``invalid`` failure
means the post itself is wrong and will be rejected identically every time.

**What may be wrapped in this.** Retrying is only safe for an operation that
either created a post or provably did not. That holds for a single call the
network answered with a structured rejection, and for the *preparation* steps
of a multi-call publisher (building an Instagram container, uploading a
LinkedIn image) — none of which put anything on a feed.

It does not hold for the call that creates the post, so Instagram and LinkedIn
run that one **outside** this helper, exactly once. Nor does it hold for the
``ambiguous`` code, which means the network accepted a post we cannot name;
that code is absent from ``RETRYABLE_CODES`` on purpose. Widening either of
those is how the same content gets posted three times.

A network-level failure (timeout, reset) is not a ``PublishError`` and so is
never retried here either: it propagates to ``PublishService``, which records
the attempt as failed rather than guessing whether the request landed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.publishing.publishers.base import PublishError

logger = logging.getLogger(__name__)

RETRYABLE_CODES = frozenset({"rate_limited", "transient"})

T = TypeVar("T")


async def with_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float,
    description: str = "publish",
) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except PublishError as exc:
            is_last = attempt + 1 >= attempts
            if exc.code not in RETRYABLE_CODES or is_last:
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "Retrying %s after %s failure (attempt %d/%d): %s",
                description,
                exc.code,
                attempt + 1,
                attempts,
                exc,
            )
            if delay:
                await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
