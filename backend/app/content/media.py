"""Post media: generate, upload, browse the library, choose what goes out.

Replaces the old per-post image service. Two model changes drive the whole
file (D9/D11 in docs/MEDIA-PLAN.md):

*Assets belong to a generation group, not to an item.* A content item is one
platform, so an image owned by the item would have to be uploaded once per
network for a single campaign. The library is therefore group-wide.

*Selection belongs to the item.* Which of those assets a post actually sends,
and in what order, is per item — which is what lets the LinkedIn variant carry
a different set from the Facebook one, while ``apply_to_group`` covers the
common case where they should match.

Bytes live on the row, so images share the database's persistence and backups —
no volume, no object store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.content.ingest import (
    MediaRejectedError,
    describe_generated,
    normalise_upload,
)
from app.content.service import ContentItemNotFoundError
from app.db.enums import ContentPlatform, MediaSource, PublishStatus
from app.db.models import (
    ContentItem,
    ContentItemMedia,
    ContentPublication,
    ContentPublicationMedia,
    Course,
    MediaAsset,
)
from app.llm.client import LLMClient
from app.llm.images import get_image_client

# The platform image ceilings live with every other platform rule, in the pure
# preflight module. Importing them costs one edge in the dependency graph and
# saves a second table that would silently disagree with the first.
from app.publishing.rules import LIMITS


class MediaAssetNotFoundError(LookupError):
    """The asset id does not exist."""


class MediaAssetInUseError(RuntimeError):
    """The asset was published; deleting it would hole our record of what is live."""


class MediaSelectionError(ValueError):
    """The requested selection is not valid for this item's platform."""


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """The saved selection, plus anything ``apply_to_group`` could not do.

    Siblings are reported rather than silently trimmed: a LinkedIn post quietly
    losing four of its six images is exactly the kind of surprise this feature
    exists to remove.
    """

    selection: list[ContentItemMedia]
    warnings: list[str]


class MediaService:
    def __init__(
        self, session: AsyncSession, llm: LLMClient, settings: Settings
    ) -> None:
        self._session = session
        self._llm = llm
        self._settings = settings

    # ── items and scope ──

    async def _get_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self._session.get(ContentItem, item_id)
        if item is None:
            raise ContentItemNotFoundError(f"Content item {item_id} not found.")
        return item

    async def _library_ids(self, item: ContentItem) -> list[uuid.UUID]:
        """Every asset this item may attach.

        The generation group when it has one; otherwise the assets already
        attached to the item, which is all a pre-group row can offer.
        """
        if item.generation_group is not None:
            result = await self._session.execute(
                select(MediaAsset.id).where(
                    MediaAsset.generation_group == item.generation_group
                )
            )
            return list(result.scalars())
        result = await self._session.execute(
            select(ContentItemMedia.media_asset_id).where(
                ContentItemMedia.content_item_id == item.id
            )
        )
        return list(result.scalars())

    async def library(self, item_id: uuid.UUID) -> list[MediaAsset]:
        """Every asset available to this post, newest first."""
        item = await self._get_item(item_id)
        ids = await self._library_ids(item)
        if not ids:
            return []
        result = await self._session.execute(
            select(MediaAsset)
            .where(MediaAsset.id.in_(ids))
            .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        )
        return list(result.scalars())

    async def selection(self, item_id: uuid.UUID) -> list[ContentItemMedia]:
        """This item's ordered selection. Empty means "text only"."""
        await self._get_item(item_id)
        return await self._selection_rows(item_id)

    async def _selection_rows(self, item_id: uuid.UUID) -> list[ContentItemMedia]:
        result = await self._session.execute(
            select(ContentItemMedia)
            .where(ContentItemMedia.content_item_id == item_id)
            .order_by(ContentItemMedia.position)
        )
        return list(result.scalars())

    async def selected_assets(self, item_id: uuid.UUID) -> list[MediaAsset]:
        """The selection resolved to assets, still in publish order."""
        rows = await self._selection_rows(item_id)
        if not rows:
            return []
        result = await self._session.execute(
            select(MediaAsset).where(
                MediaAsset.id.in_([row.media_asset_id for row in rows])
            )
        )
        by_id = {asset.id: asset for asset in result.scalars()}
        return [by_id[row.media_asset_id] for row in rows if row.media_asset_id in by_id]

    async def _auto_attach(self, item: ContentItem, asset_id: uuid.UUID) -> None:
        """Append a just-created asset to the selection of the post it came from.

        Making an image *for* a post and having it not go out would be the same
        invisible behaviour D11 exists to remove — only inverted. So a new asset
        joins the selection immediately, visibly ticked in the panel, where the
        operator can reorder or untick it.

        Two exits: the post is already at its platform's ceiling (the operator
        chooses what to drop, we do not), or the asset is somehow attached
        already.
        """
        existing = await self._selection_rows(item.id)
        if len(existing) >= LIMITS[item.platform].max_images:
            return
        if any(row.media_asset_id == asset_id for row in existing):
            return
        self._session.add(
            ContentItemMedia(
                id=uuid.uuid4(),
                content_item_id=item.id,
                media_asset_id=asset_id,
                position=len(existing),
            )
        )
        await self._session.flush()

    # ── generate ──

    async def _suggestion_context(self, item: ContentItem) -> dict:
        context: dict = {
            "platform": item.platform.value,
            "post_body": item.edited_body or item.generated_body,
            "topic": item.topic,
        }
        if item.course_id is not None:
            course = await self._session.get(Course, item.course_id)
            if course is not None:
                context["course"] = {
                    "title": course.title,
                    "category": course.category,
                }
        return context

    async def suggest_prompts(self, item_id: uuid.UUID) -> list[str]:
        item = await self._get_item(item_id)
        return await self._llm.suggest_image_prompts(
            await self._suggestion_context(item)
        )

    async def generate(
        self, item_id: uuid.UUID, *, prompt: str, actor_id: uuid.UUID | None
    ) -> MediaAsset:
        item = await self._get_item(item_id)
        client = get_image_client(self._settings)
        png = await client.generate_image(prompt)
        measured = describe_generated(png)

        asset = MediaAsset(
            id=uuid.uuid4(),
            generation_group=item.generation_group,
            source=MediaSource.generated,
            prompt=prompt,
            model="mock" if self._settings.llm_mock else self._settings.image_model,
            mime_type=measured.mime_type,
            width=measured.width,
            height=measured.height,
            byte_size=measured.byte_size,
            checksum=measured.checksum,
            alt_text=prompt[:300],
            data=png,
            created_by=actor_id,
        )
        self._session.add(asset)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_image.generate",
            entity_type="media_asset",
            entity_id=asset.id,
            payload_diff={"content_item_id": str(item.id), "prompt": prompt},
        )
        await self._session.flush()
        await self._auto_attach(item, asset.id)
        return asset

    # ── upload ──

    async def upload(
        self,
        item_id: uuid.UUID,
        *,
        data: bytes,
        filename: str | None,
        actor_id: uuid.UUID | None,
    ) -> MediaAsset:
        """Normalise one uploaded file into the item's library.

        Re-uploading a file already in the group returns the existing asset
        rather than a second copy of the same bytes — the operator dragging the
        same folder in twice is a mistake, not an instruction.
        """
        item = await self._get_item(item_id)
        if len(data) > self._settings.media_upload_max_bytes:
            raise MediaRejectedError(
                f"That file is {len(data) // 1024} KB; the limit is "
                f"{self._settings.media_upload_max_bytes // 1024} KB."
            )

        existing_ids = await self._library_ids(item)
        if len(existing_ids) >= self._settings.media_max_assets_per_group:
            raise MediaRejectedError(
                f"This generation already holds "
                f"{self._settings.media_max_assets_per_group} images. Delete "
                "some before adding more."
            )

        normalised = normalise_upload(
            data,
            filename=filename,
            max_dimension=self._settings.media_max_dimension,
        )

        if existing_ids:
            duplicate = await self._session.execute(
                select(MediaAsset)
                .where(MediaAsset.id.in_(existing_ids))
                .where(MediaAsset.checksum == normalised.checksum)
                .limit(1)
            )
            already = duplicate.scalars().first()
            if already is not None:
                await self._auto_attach(item, already.id)
                return already

        asset = MediaAsset(
            id=uuid.uuid4(),
            generation_group=item.generation_group,
            source=MediaSource.uploaded,
            prompt=None,
            model=None,
            filename=normalised.filename,
            mime_type=normalised.mime_type,
            width=normalised.width,
            height=normalised.height,
            byte_size=normalised.byte_size,
            checksum=normalised.checksum,
            data=normalised.data,
            created_by=actor_id,
        )
        self._session.add(asset)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="media_asset.upload",
            entity_type="media_asset",
            entity_id=asset.id,
            payload_diff={
                "content_item_id": str(item.id),
                "filename": normalised.filename,
                "bytes": normalised.byte_size,
                "dimensions": f"{normalised.width}x{normalised.height}",
            },
        )
        await self._session.flush()
        await self._auto_attach(item, asset.id)
        return asset

    # ── selection ──

    def _check_limit(self, platform: ContentPlatform, count: int) -> None:
        limit = LIMITS[platform].max_images
        if count > limit:
            raise MediaSelectionError(
                f"{platform.value.title()} accepts at most {limit} images; "
                f"{count} were selected."
            )

    async def _write_selection(
        self, item: ContentItem, asset_ids: list[uuid.UUID]
    ) -> list[ContentItemMedia]:
        """Replace an item's whole selection. Callers hold the transaction.

        Delete-then-insert rather than a diff: it is one statement plus one
        batch, the order is rewritten wholesale anyway, and no intermediate
        state with duplicate positions is ever visible.
        """
        await self._session.execute(
            delete(ContentItemMedia).where(
                ContentItemMedia.content_item_id == item.id
            )
        )
        rows = [
            ContentItemMedia(
                id=uuid.uuid4(),
                content_item_id=item.id,
                media_asset_id=asset_id,
                position=position,
            )
            for position, asset_id in enumerate(asset_ids)
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    async def set_selection(
        self,
        item_id: uuid.UUID,
        *,
        asset_ids: list[uuid.UUID],
        actor_id: uuid.UUID | None,
        apply_to_group: bool = False,
    ) -> SelectionResult:
        item = await self._get_item(item_id)

        if len(set(asset_ids)) != len(asset_ids):
            raise MediaSelectionError("The same image was selected twice.")
        available = set(await self._library_ids(item))
        unknown = [str(a) for a in asset_ids if a not in available]
        if unknown:
            raise MediaSelectionError(
                "Some images are not available to this post: " + ", ".join(unknown)
            )
        self._check_limit(item.platform, len(asset_ids))

        selection = await self._write_selection(item, asset_ids)
        warnings: list[str] = []
        applied: list[str] = []

        if apply_to_group and item.generation_group is not None:
            siblings = await self._session.execute(
                select(ContentItem).where(
                    ContentItem.generation_group == item.generation_group,
                    ContentItem.id != item.id,
                )
            )
            for sibling in siblings.scalars():
                # Published posts are never touched: our copy of what is live
                # on someone else's server must not drift from theirs.
                if sibling.status.value == "published":
                    warnings.append(
                        f"{sibling.platform.value.title()} is already published "
                        "and was left alone."
                    )
                    continue
                limit = LIMITS[sibling.platform].max_images
                if len(asset_ids) > limit:
                    warnings.append(
                        f"{sibling.platform.value.title()} accepts at most "
                        f"{limit} images, so its selection was left alone."
                    )
                    continue
                await self._write_selection(sibling, asset_ids)
                applied.append(sibling.platform.value)

        record_audit(
            self._session,
            actor_id=actor_id,
            action="media_selection.set",
            entity_type="content_item",
            entity_id=item.id,
            payload_diff={
                "asset_ids": [str(a) for a in asset_ids],
                "applied_to": applied,
            },
        )
        return SelectionResult(selection=selection, warnings=warnings)

    # ── assets ──

    async def get_asset(self, asset_id: uuid.UUID) -> MediaAsset:
        asset = await self._session.get(MediaAsset, asset_id)
        if asset is None:
            raise MediaAssetNotFoundError(f"Image {asset_id} not found.")
        return asset

    async def delete_asset(
        self, asset_id: uuid.UUID, *, actor_id: uuid.UUID | None
    ) -> None:
        asset = await self.get_asset(asset_id)
        published = await self._session.execute(
            select(ContentPublicationMedia.id)
            .join(
                ContentPublication,
                ContentPublication.id == ContentPublicationMedia.publication_id,
            )
            .where(
                ContentPublicationMedia.media_asset_id == asset.id,
                ContentPublication.status == PublishStatus.succeeded,
            )
            .limit(1)
        )
        if published.scalars().first() is not None:
            raise MediaAssetInUseError(
                "This image has been published. It stays here so the record of "
                "what went out is complete."
            )
        record_audit(
            self._session,
            actor_id=actor_id,
            action="media_asset.delete",
            entity_type="media_asset",
            entity_id=asset.id,
            payload_diff={"filename": asset.filename, "source": asset.source.value},
        )
        # Which posts had it selected, read before it goes: their positions
        # need closing up afterwards.
        affected = list(
            (
                await self._session.execute(
                    select(ContentItemMedia.content_item_id)
                    .where(ContentItemMedia.media_asset_id == asset.id)
                    .distinct()
                )
            ).scalars()
        )

        # The two dependent tables are cleared here rather than left to the
        # database. The FKs declare CASCADE and SET NULL, but SQLite does not
        # enforce foreign keys by default and the ORM does not cascade to rows
        # it has no relationship for — so relying on either would leave the
        # test suite and production disagreeing about what a delete does.
        await self._session.execute(
            delete(ContentItemMedia).where(
                ContentItemMedia.media_asset_id == asset.id
            )
        )
        await self._session.execute(
            update(ContentPublicationMedia)
            .where(ContentPublicationMedia.media_asset_id == asset.id)
            .values(media_asset_id=None)
        )
        await self._session.delete(asset)
        await self._session.flush()

        # Positions are the carousel order, so a selection left running 0, 2, 3
        # is not wrong exactly — but it invites an off-by-one the first time
        # anything reads a position as an index.
        for item_id in affected:
            for position, row in enumerate(await self._selection_rows(item_id)):
                row.position = position
        await self._session.flush()
