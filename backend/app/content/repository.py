"""Content item persistence (thin repository, no business rules)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContentPlatform, ContentStatus
from app.db.models import ContentItem


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, item: ContentItem) -> ContentItem:
        self._session.add(item)
        return item

    async def get(self, item_id: uuid.UUID) -> ContentItem | None:
        return (
            await self._session.execute(
                select(ContentItem).where(ContentItem.id == item_id)
            )
        ).scalar_one_or_none()

    async def list_items(
        self,
        *,
        platform: ContentPlatform | None = None,
        status: ContentStatus | None = None,
        course_id: uuid.UUID | None = None,
        generation_group: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[ContentItem]:
        query = select(ContentItem).order_by(ContentItem.created_at.desc()).limit(limit)
        if platform is not None:
            query = query.where(ContentItem.platform == platform)
        if status is not None:
            query = query.where(ContentItem.status == status)
        if course_id is not None:
            query = query.where(ContentItem.course_id == course_id)
        if generation_group is not None:
            query = query.where(ContentItem.generation_group == generation_group)
        return list((await self._session.execute(query)).scalars().all())
