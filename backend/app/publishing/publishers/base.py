"""The publisher seam: one protocol covering all three networks.

``PublishService`` depends only on ``Publisher``, so the mock, the three live
implementations, and any test double are interchangeable. Everything crossing
this boundary is a frozen dataclass — a publisher receives exactly what it
needs to make one call and returns exactly what we persist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.db.enums import ContentPlatform

# Failure categories the UI reacts to differently. `reauth` drives "Reconnect
# the Page", `rate_limited` and `transient` mean "try again later", `invalid`
# means the post itself is wrong and retrying will not help.
#
# `ambiguous` is the dangerous one and is deliberately its own code rather than
# a flavour of `transient`: the network accepted the post but did not tell us
# what it is called. Something is probably live. Retrying that automatically
# posts it twice, so `ambiguous` is never retried and the message always tells
# the operator to look at the account before trying again.
PublishErrorCode = Literal[
    "reauth",
    "rate_limited",
    "transient",
    "ambiguous",
    "invalid",
    "unreachable_media",
    "not_configured",
]


class PublishError(RuntimeError):
    """A publish attempt failed. ``code`` drives how the UI phrases it."""

    def __init__(self, message: str, *, code: PublishErrorCode = "transient") -> None:
        super().__init__(message)
        self.code: PublishErrorCode = code


@dataclass(frozen=True, slots=True)
class ResolvedAccount:
    """A connected destination with its token already decrypted."""

    id: str
    platform: ContentPlatform
    external_id: str
    display_name: str
    access_token: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PublishRequest:
    text: str
    account: ResolvedAccount
    # Signed, short-lived, publicly fetchable. Instagram can use nothing else;
    # Facebook and LinkedIn upload `image_bytes` instead.
    image_url: str | None = None
    # Always JPEG, converted once by the service, so every network receives
    # exactly the bytes the signed URL would serve.
    image_bytes: bytes | None = None
    image_alt: str | None = None
    link: str | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    external_post_id: str
    permalink: str | None = None


class Publisher(Protocol):
    async def publish(self, request: PublishRequest) -> PublishResult:
        """Post to the network, or raise ``PublishError``."""
        ...


class AccountVerifier(Protocol):
    """Liveness check for a stored connection.

    Kept off the ``Publisher`` protocol on purpose: asking "is this token still
    good?" is not part of posting, and the publish seam should stay narrow
    enough that a test double only has to implement one method.
    """

    async def verify(self, account: ResolvedAccount) -> None:
        """Return normally if the credentials still work, else raise."""
        ...
