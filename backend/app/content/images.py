"""Post-image service: LLM prompt suggestions, generation, per-post history.

Files land under ``<media_dir>/content_images/<uuid>.png`` (uuid-named, never
derived from user input); the DB row stores the media-relative path so the
media root can move without a data migration.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.content.service import ContentItemNotFoundError
from app.db.models import ContentImage, ContentItem, Course
from app.llm.client import LLMClient
from app.llm.images import get_image_client

_IMAGES_SUBDIR = "content_images"


class ContentImageNotFoundError(LookupError):
    """Raised when an image id does not exist."""


def media_root(settings: Settings) -> Path:
    return Path(settings.media_dir).expanduser().resolve()


class ContentImageService:
    def __init__(
        self, session: AsyncSession, llm: LLMClient, settings: Settings
    ) -> None:
        self._session = session
        self._llm = llm
        self._settings = settings

    async def _get_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self._session.get(ContentItem, item_id)
        if item is None:
            raise ContentItemNotFoundError(f"Content item {item_id} not found.")
        return item

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
    ) -> ContentImage:
        item = await self._get_item(item_id)
        client = get_image_client(self._settings)
        png = await client.generate_image(prompt)

        image_id = uuid.uuid4()
        relative_path = f"{_IMAGES_SUBDIR}/{image_id}.png"
        target = media_root(self._settings) / _IMAGES_SUBDIR / f"{image_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png)

        image = ContentImage(
            id=image_id,
            content_item_id=item.id,
            prompt=prompt,
            model="mock" if self._settings.llm_mock else self._settings.image_model,
            file_path=relative_path,
            created_by=actor_id,
        )
        self._session.add(image)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_image.generate",
            entity_type="content_image",
            entity_id=image_id,
            payload_diff={"content_item_id": str(item.id), "prompt": prompt},
        )
        await self._session.flush()
        return image

    async def list_images(self, item_id: uuid.UUID) -> list[ContentImage]:
        await self._get_item(item_id)  # 404 for unknown posts, not an empty list
        result = await self._session.execute(
            select(ContentImage)
            .where(ContentImage.content_item_id == item_id)
            .order_by(ContentImage.created_at.desc(), ContentImage.id.desc())
        )
        return list(result.scalars())

    async def get_image(self, image_id: uuid.UUID) -> ContentImage:
        image = await self._session.get(ContentImage, image_id)
        if image is None:
            raise ContentImageNotFoundError(f"Image {image_id} not found.")
        return image

    def image_file(self, image: ContentImage) -> Path:
        """Resolve the stored relative path safely under the media root."""
        root = media_root(self._settings)
        path = (root / image.file_path).resolve()
        if not path.is_relative_to(root):
            raise ContentImageNotFoundError("Image file path is invalid.")
        if not path.is_file():
            raise ContentImageNotFoundError("Image file is missing from storage.")
        return path
