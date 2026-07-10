"""Process-local sliding-window rate limit for the login endpoint.

Login is the only unauthenticated mutation, so it gets a dedicated brute-force
guard. In-memory is deliberate: a single-process deployment needs no Redis,
and the limiter resets on restart, which is acceptable for this threat model.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, max_hits: int, window_seconds: int) -> bool:
        """Record a hit and return True while the caller is within the limit."""
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= max_hits:
            return False
        window.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


_limiter = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _limiter


async def login_rate_limit(request: Request) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    allowed = _limiter.check(
        f"login:{client_ip}",
        max_hits=settings.login_rate_limit_max,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait and try again.",
        )
