"""Publisher selection and the offline mock."""

from __future__ import annotations

import pytest

from app.db.enums import ContentPlatform
from app.publishing.publishers import PublishError, get_publisher
from app.publishing.publishers.base import PublishRequest, ResolvedAccount
from app.publishing.publishers.facebook import FacebookPublisher
from app.publishing.publishers.instagram import InstagramPublisher
from app.publishing.publishers.linkedin import LinkedInPublisher
from app.publishing.publishers.mock import MockPublisher
from tests.conftest import make_settings

ALL_PLATFORMS = list(ContentPlatform)


def _request(platform: ContentPlatform, text: str = "Enrol now.") -> PublishRequest:
    return PublishRequest(
        text=text,
        account=ResolvedAccount(
            id="account-1",
            platform=platform,
            external_id="wrcc-page-1",
            display_name="WRCC",
            access_token="token",
        ),
    )


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_mock_publisher_is_selected_by_default(platform: ContentPlatform) -> None:
    assert isinstance(get_publisher(platform, make_settings()), MockPublisher)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (ContentPlatform.facebook, FacebookPublisher),
        (ContentPlatform.instagram, InstagramPublisher),
        (ContentPlatform.linkedin, LinkedInPublisher),
    ],
)
def test_live_mode_selects_the_platform_publisher(
    platform: ContentPlatform, expected: type
) -> None:
    settings = make_settings(
        publish_mock=False,
        meta_app_id="x",
        meta_app_secret="x",
        linkedin_client_id="x",
        linkedin_client_secret="x",
    )
    assert isinstance(get_publisher(platform, settings), expected)


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
async def test_mock_publish_is_deterministic(platform: ContentPlatform) -> None:
    publisher = MockPublisher(platform)
    first = await publisher.publish(_request(platform))
    second = await publisher.publish(_request(platform))
    assert first == second


async def test_mock_publish_varies_with_the_text() -> None:
    publisher = MockPublisher(ContentPlatform.facebook)
    first = await publisher.publish(_request(ContentPlatform.facebook, "one"))
    second = await publisher.publish(_request(ContentPlatform.facebook, "two"))
    assert first.external_post_id != second.external_post_id


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
async def test_mock_permalink_matches_the_platform(
    platform: ContentPlatform,
) -> None:
    result = await MockPublisher(platform).publish(_request(platform))
    assert result.permalink is not None
    assert platform.value in result.permalink
    assert result.external_post_id in result.permalink


def test_publish_error_defaults_to_transient() -> None:
    # An uncategorised failure should read as "try again", not "give up".
    assert PublishError("something went wrong").code == "transient"
