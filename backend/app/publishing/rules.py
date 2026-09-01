"""Preflight rules — pure, and the single source of truth for "can this go out?".

Every rule here runs *before* any network call, so a post that a network would
reject is refused by us with a readable reason instead of failing halfway
through a Graph conversation. The frontend calls the preflight endpoint rather
than re-implementing this table, which is the only way to keep the two from
drifting when a platform changes a limit.

No I/O and no ORM objects cross this boundary: the caller reduces the world to
a ``PreflightContext`` and these functions decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.enums import ContentPlatform, ContentStatus


@dataclass(frozen=True, slots=True)
class PlatformLimits:
    text_limit: int
    hashtag_limit: int
    # Instagram has no text-only feed post: an image is part of the contract.
    image_required: bool
    # Above this many hashtags we warn; above `hashtag_limit` we block.
    hashtag_warn_above: int


# Facebook and LinkedIn publish no hashtag ceiling of their own, so 100 is ours:
# high enough that no sane post reaches it, low enough to catch a generation
# that has clearly gone wrong. Instagram's 30 is a real, enforced API limit.
LIMITS: dict[ContentPlatform, PlatformLimits] = {
    ContentPlatform.facebook: PlatformLimits(
        text_limit=63_206, hashtag_limit=100, image_required=False, hashtag_warn_above=10
    ),
    ContentPlatform.instagram: PlatformLimits(
        text_limit=2_200, hashtag_limit=30, image_required=True, hashtag_warn_above=15
    ),
    ContentPlatform.linkedin: PlatformLimits(
        text_limit=3_000, hashtag_limit=100, image_required=False, hashtag_warn_above=5
    ),
}


@dataclass(frozen=True, slots=True)
class PreflightContext:
    platform: ContentPlatform
    status: ContentStatus
    text: str
    hashtag_count: int = 0
    has_image: bool = False
    # Spec violations the media layer could not fix for us (aspect ratio, an
    # image too small to post). Reported verbatim — they are already phrased
    # for the operator.
    image_problems: list[str] = field(default_factory=list)
    account_connected: bool = False
    account_token_expired: bool = False
    already_published: bool = False
    # An attempt that has not reported back. Blocks either way — the wording
    # changes because "still running" and "we lost the response" call for very
    # different reactions from the person at the keyboard.
    has_pending_attempt: bool = False
    pending_attempt_is_stale: bool = False


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blockers


def compose_post_text(body: str, call_to_action: str | None, hashtags: list[str]) -> str:
    """Assemble the single blob of text a network expects.

    The backend twin of ``frontend/lib/postText.ts`` — the two must agree, or
    the preview shows something other than what gets posted. Hashtags last, CTA
    between them and the body so the ask is not buried under the tags.
    """
    tags = " ".join(tag.strip() for tag in hashtags if tag.strip())
    sections = [body.strip(), (call_to_action or "").strip(), tags]
    return "\n\n".join(section for section in sections if section)


def preflight(context: PreflightContext) -> PreflightOutcome:
    """Return every reason this post cannot (or should not) go out."""
    limits = LIMITS[context.platform]
    blockers: list[str] = []
    warnings: list[str] = []

    if context.status is ContentStatus.published or context.already_published:
        blockers.append("This post has already been published.")
    elif context.status is not ContentStatus.approved:
        blockers.append(
            f"Only approved posts can be published (this one is "
            f"'{context.status.value}')."
        )

    if context.has_pending_attempt:
        blockers.append(
            f"An earlier attempt never reported back — check {context.platform.value} "
            "for the post before retrying."
            if context.pending_attempt_is_stale
            else "A publish attempt for this post is still running."
        )

    if not context.account_connected:
        blockers.append(
            f"No {context.platform.value} account is connected. "
            "Connect one in Settings."
        )
    elif context.account_token_expired:
        blockers.append(
            f"The {context.platform.value} connection has expired. "
            "Reconnect it in Settings."
        )

    if limits.image_required and not context.has_image:
        blockers.append(
            f"{context.platform.value.title()} posts require an image. "
            "Generate one first."
        )
    elif limits.image_required:
        blockers.extend(context.image_problems)

    text_length = len(context.text)
    if text_length == 0:
        blockers.append("The post is empty.")
    elif text_length > limits.text_limit:
        blockers.append(
            f"The post is {text_length} characters; "
            f"{context.platform.value} allows {limits.text_limit}."
        )

    if context.hashtag_count > limits.hashtag_limit:
        blockers.append(
            f"{context.hashtag_count} hashtags; "
            f"{context.platform.value} allows {limits.hashtag_limit}."
        )
    elif context.hashtag_count > limits.hashtag_warn_above:
        warnings.append(
            f"{context.hashtag_count} hashtags is more than usually performs "
            f"well on {context.platform.value}."
        )

    return PreflightOutcome(blockers=blockers, warnings=warnings)
