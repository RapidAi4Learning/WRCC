"""Upload, library and selection through the API.

Two behaviours carry most of the weight here:

*The library is the generation group.* An image uploaded for the Facebook
variant is offered to the Instagram and LinkedIn variants of the same
generation, so a campaign is not uploaded three times.

*The selection is the post.* What goes out is what is ticked, in the order it is
ticked — never "whatever was most recent", which is the invisible rule this
phase removes.
"""

from __future__ import annotations

import io

from httpx import AsyncClient
from PIL import Image

from app.db.enums import ContentPlatform
from tests.conftest import connect_social_account


def _image_bytes(
    width: int = 640, height: int = 640, fmt: str = "JPEG", colour=(30, 90, 150)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format=fmt)
    return buffer.getvalue()


def _upload_files(count: int = 1, **kwargs) -> list[tuple[str, tuple]]:
    return [
        (
            "files",
            (
                f"photo-{index + 1}.jpg",
                _image_bytes(colour=(index * 20, 90, 150), **kwargs),
                "image/jpeg",
            ),
        )
        for index in range(count)
    ]


async def _generate(
    auth_client: AsyncClient, platforms: list[str] | None = None
) -> list[dict]:
    response = await auth_client.post(
        "/api/content/generate",
        json={
            "topic": "First aid enrolments",
            "platforms": platforms or ["facebook"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _item_id(auth_client: AsyncClient) -> str:
    return (await _generate(auth_client))[0]["id"]


async def _upload(auth_client: AsyncClient, item_id: str, count: int = 1):
    return await auth_client.post(
        f"/api/content/{item_id}/media", files=_upload_files(count)
    )


# ── auth ──


async def test_upload_requires_a_session(client: AsyncClient) -> None:
    response = await client.post(
        "/api/content/00000000-0000-0000-0000-000000000000/media",
        files=_upload_files(),
    )
    assert response.status_code == 401


# ── upload ──


async def test_upload_stores_an_asset_and_serves_it_back(
    auth_client: AsyncClient,
) -> None:
    item_id = await _item_id(auth_client)

    response = await _upload(auth_client, item_id)

    assert response.status_code == 200, response.text
    assets = response.json()
    assert len(assets) == 1
    asset = assets[0]
    assert asset["source"] == "uploaded"
    assert asset["prompt"] is None  # an upload has no prompt, by construction
    assert asset["model"] is None
    assert asset["filename"] == "photo-1.jpg"
    assert asset["mime_type"] == "image/jpeg"
    assert asset["width"] == 640

    served = await auth_client.get(asset["file_url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    # The bytes are no longer all PNGs of our own making, so the browser must
    # not be left to guess.
    assert served.headers["x-content-type-options"] == "nosniff"

    download = await auth_client.get(asset["file_url"], params={"download": "true"})
    assert download.headers["content-disposition"].endswith('.jpg"')


async def test_several_files_upload_in_one_request(auth_client: AsyncClient) -> None:
    item_id = await _item_id(auth_client)

    response = await _upload(auth_client, item_id, count=3)

    assert response.status_code == 200, response.text
    assert len({asset["id"] for asset in response.json()}) == 3


async def test_a_non_image_is_refused_with_a_readable_reason(
    auth_client: AsyncClient,
) -> None:
    item_id = await _item_id(auth_client)

    response = await auth_client.post(
        f"/api/content/{item_id}/media",
        # Declared as a PNG. The declaration is not consulted.
        files=[("files", ("payload.png", b"#!/bin/sh\necho hi", "image/png"))],
    )

    assert response.status_code == 400
    assert "PNG, JPEG or WebP" in response.json()["detail"]


async def test_an_oversized_file_is_refused(auth_client: AsyncClient, app) -> None:
    from app.config import get_settings
    from tests.conftest import make_settings

    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_upload_max_bytes=1024
    )
    item_id = await _item_id(auth_client)

    response = await auth_client.post(
        f"/api/content/{item_id}/media",
        files=[("files", ("big.jpg", _image_bytes(2000, 2000), "image/jpeg"))],
    )

    assert response.status_code == 400
    assert "limit" in response.json()["detail"]


async def test_re_uploading_the_same_file_does_not_store_it_twice(
    auth_client: AsyncClient,
) -> None:
    # Dragging the same folder in twice is a slip, not an instruction.
    item_id = await _item_id(auth_client)
    first = (await _upload(auth_client, item_id)).json()[0]

    second = (await _upload(auth_client, item_id)).json()[0]

    assert second["id"] == first["id"]
    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert len(library["library"]) == 1


async def test_the_group_asset_cap_is_enforced(auth_client: AsyncClient, app) -> None:
    from app.config import get_settings
    from tests.conftest import make_settings

    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_max_assets_per_group=2
    )
    item_id = await _item_id(auth_client)
    await _upload(auth_client, item_id, count=2)

    response = await auth_client.post(
        f"/api/content/{item_id}/media",
        files=[("files", ("third.jpg", _image_bytes(colour=(9, 9, 9)), "image/jpeg"))],
    )

    assert response.status_code == 400
    assert "Delete some" in response.json()["detail"]


# ── the library is the generation group ──


async def test_an_upload_is_available_to_the_other_platforms_of_the_generation(
    auth_client: AsyncClient,
) -> None:
    items = await _generate(auth_client, ["facebook", "instagram", "linkedin"])
    facebook = next(item for item in items if item["platform"] == "facebook")
    linkedin = next(item for item in items if item["platform"] == "linkedin")

    uploaded = (await _upload(auth_client, facebook["id"])).json()[0]

    library = (await auth_client.get(f"/api/content/{linkedin['id']}/media")).json()
    assert uploaded["id"] in {asset["id"] for asset in library["library"]}
    # Available, but not silently attached: LinkedIn sends what LinkedIn ticks.
    assert library["selection"] == []


async def test_an_asset_from_a_different_generation_is_not_offered(
    auth_client: AsyncClient,
) -> None:
    mine = await _item_id(auth_client)
    theirs = await _item_id(auth_client)
    foreign = (await _upload(auth_client, theirs)).json()[0]

    library = (await auth_client.get(f"/api/content/{mine}/media")).json()

    assert foreign["id"] not in {asset["id"] for asset in library["library"]}


# ── selection ──


async def test_a_new_asset_joins_the_selection_of_the_post_it_came_from(
    auth_client: AsyncClient,
) -> None:
    # Making an image *for* a post and having it not go out would be the same
    # invisible behaviour, only inverted.
    item_id = await _item_id(auth_client)

    uploaded = (await _upload(auth_client, item_id)).json()[0]

    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert [row["media_asset_id"] for row in library["selection"]] == [uploaded["id"]]


async def test_selection_is_replaced_in_the_order_given(
    auth_client: AsyncClient,
) -> None:
    item_id = await _item_id(auth_client)
    assets = (await _upload(auth_client, item_id, count=3)).json()
    reordered = [assets[2]["id"], assets[0]["id"]]

    response = await auth_client.put(
        f"/api/content/{item_id}/media/selection", json={"asset_ids": reordered}
    )

    assert response.status_code == 200, response.text
    saved = response.json()["selection"]
    assert [row["media_asset_id"] for row in saved] == reordered
    assert [row["position"] for row in saved] == [0, 1]


async def test_an_empty_selection_is_a_real_choice(auth_client: AsyncClient) -> None:
    item_id = await _item_id(auth_client)
    await _upload(auth_client, item_id)

    response = await auth_client.put(
        f"/api/content/{item_id}/media/selection", json={"asset_ids": []}
    )

    assert response.status_code == 200
    assert response.json()["selection"] == []
    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert len(library["library"]) == 1  # still there, just not going out


async def test_selecting_the_same_image_twice_is_refused(
    auth_client: AsyncClient,
) -> None:
    item_id = await _item_id(auth_client)
    asset = (await _upload(auth_client, item_id)).json()[0]

    response = await auth_client.put(
        f"/api/content/{item_id}/media/selection",
        json={"asset_ids": [asset["id"], asset["id"]]},
    )

    assert response.status_code == 422
    assert "twice" in response.json()["detail"]


async def test_an_asset_outside_the_group_cannot_be_selected(
    auth_client: AsyncClient,
) -> None:
    mine = await _item_id(auth_client)
    theirs = await _item_id(auth_client)
    foreign = (await _upload(auth_client, theirs)).json()[0]

    response = await auth_client.put(
        f"/api/content/{mine}/media/selection", json={"asset_ids": [foreign["id"]]}
    )

    assert response.status_code == 422
    assert "not available" in response.json()["detail"]


async def test_the_platform_ceiling_is_reported_and_enforced(
    auth_client: AsyncClient, app
) -> None:
    from app.config import get_settings
    from tests.conftest import make_settings

    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_max_assets_per_group=40
    )
    items = await _generate(auth_client, ["instagram"])
    item_id = items[0]["id"]
    assets = (await _upload(auth_client, item_id, count=11)).json()

    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert library["max_images"] == 10  # so the UI can disable the checkbox

    response = await auth_client.put(
        f"/api/content/{item_id}/media/selection",
        json={"asset_ids": [asset["id"] for asset in assets]},
    )

    assert response.status_code == 422
    assert "at most 10" in response.json()["detail"]


async def test_auto_attach_stops_at_the_platform_ceiling(
    auth_client: AsyncClient,
) -> None:
    # Past the limit the operator decides what to drop; we do not silently
    # evict something they chose.
    items = await _generate(auth_client, ["instagram"])
    item_id = items[0]["id"]

    assets = (await _upload(auth_client, item_id, count=11)).json()

    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert len(library["library"]) == 11
    assert len(library["selection"]) == 10
    assert assets[10]["id"] not in {
        row["media_asset_id"] for row in library["selection"]
    }


# ── apply to the rest of the generation ──


async def test_apply_to_group_copies_the_selection_to_the_siblings(
    auth_client: AsyncClient,
) -> None:
    items = await _generate(auth_client, ["facebook", "instagram"])
    facebook = next(item for item in items if item["platform"] == "facebook")
    instagram = next(item for item in items if item["platform"] == "instagram")
    assets = (await _upload(auth_client, facebook["id"], count=2)).json()
    ids = [asset["id"] for asset in assets]

    response = await auth_client.put(
        f"/api/content/{facebook['id']}/media/selection",
        json={"asset_ids": ids, "apply_to_group": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["warnings"] == []
    sibling = (await auth_client.get(f"/api/content/{instagram['id']}/media")).json()
    assert [row["media_asset_id"] for row in sibling["selection"]] == ids


async def test_selections_stay_independent_after_apply_to_group(
    auth_client: AsyncClient,
) -> None:
    # The whole reason `apply_to_group` is an action and not a schema property:
    # Facebook and Instagram can be made to match, then LinkedIn can differ.
    items = await _generate(auth_client, ["facebook", "linkedin"])
    facebook = next(item for item in items if item["platform"] == "facebook")
    linkedin = next(item for item in items if item["platform"] == "linkedin")
    assets = (await _upload(auth_client, facebook["id"], count=2)).json()
    ids = [asset["id"] for asset in assets]
    await auth_client.put(
        f"/api/content/{facebook['id']}/media/selection",
        json={"asset_ids": ids, "apply_to_group": True},
    )

    await auth_client.put(
        f"/api/content/{linkedin['id']}/media/selection",
        json={"asset_ids": [ids[1]]},
    )

    facebook_media = (
        await auth_client.get(f"/api/content/{facebook['id']}/media")
    ).json()
    linkedin_media = (
        await auth_client.get(f"/api/content/{linkedin['id']}/media")
    ).json()
    assert [row["media_asset_id"] for row in facebook_media["selection"]] == ids
    assert [row["media_asset_id"] for row in linkedin_media["selection"]] == [ids[1]]


async def test_a_published_sibling_is_named_and_left_alone(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    # Our copy of what is live on someone else's server must not drift.
    items = await _generate(auth_client, ["facebook", "linkedin"])
    facebook = next(item for item in items if item["platform"] == "facebook")
    linkedin = next(item for item in items if item["platform"] == "linkedin")
    assets = (await _upload(auth_client, linkedin["id"], count=2)).json()

    await auth_client.post(f"/api/content/{facebook['id']}/submit")
    await auth_client.post(f"/api/content/{facebook['id']}/approve")
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    published = await auth_client.post(f"/api/content/{facebook['id']}/publish")
    assert published.status_code == 200, published.text

    response = await auth_client.put(
        f"/api/content/{linkedin['id']}/media/selection",
        json={
            "asset_ids": [asset["id"] for asset in assets],
            "apply_to_group": True,
        },
    )

    assert response.status_code == 200
    assert any("already published" in w for w in response.json()["warnings"])


# ── deleting ──


async def test_an_asset_can_be_deleted_from_the_library(
    auth_client: AsyncClient,
) -> None:
    item_id = await _item_id(auth_client)
    asset = (await _upload(auth_client, item_id)).json()[0]

    response = await auth_client.delete(f"/api/content/media/{asset['id']}")

    assert response.status_code == 204
    library = (await auth_client.get(f"/api/content/{item_id}/media")).json()
    assert library["library"] == []
    assert library["selection"] == []  # the cascade took the selection with it


async def test_a_published_asset_cannot_be_deleted(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    items = await _generate(auth_client, ["facebook"])
    item_id = items[0]["id"]
    asset = (await _upload(auth_client, item_id)).json()[0]
    await auth_client.post(f"/api/content/{item_id}/submit")
    await auth_client.post(f"/api/content/{item_id}/approve")
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    assert (await auth_client.post(f"/api/content/{item_id}/publish")).status_code == 200

    response = await auth_client.delete(f"/api/content/media/{asset['id']}")

    assert response.status_code == 409
    assert "record of what went out" in response.json()["detail"]
