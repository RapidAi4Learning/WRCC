"""Catalog + scraper-run persistence (thin repository, no business rules)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ScraperRunStatus
from app.db.models import Course, CourseOffering, ScraperRun
from app.scraper.diff import COURSE_FIELDS, OFFERING_FIELDS


def _date_from_iso(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def _removed_code(entry: object, key: str) -> str | None:
    """Read the code out of a ``*_removed`` entry.

    Entries carry identifying context now, but a run staged before that change
    can still be sitting in review with bare code strings — approving it must
    not blow up.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        code = entry.get(key)
        return code if isinstance(code, str) else None
    return None


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_live_state(self) -> list[dict]:
        """All courses (+offerings) as plain dicts for the pure diff."""
        courses = (await self._session.execute(select(Course))).scalars().all()
        offerings = (
            (await self._session.execute(select(CourseOffering))).scalars().all()
        )
        by_course: dict[uuid.UUID, list[dict]] = {}
        for offering in offerings:
            payload = {
                "offering_code": offering.offering_code,
                "is_active": offering.is_active,
                **{field: getattr(offering, field) for field in OFFERING_FIELDS},
            }
            by_course.setdefault(offering.course_id, []).append(payload)

        return [
            {
                "course_code": course.course_code,
                "is_active": course.is_active,
                **{field: getattr(course, field) for field in COURSE_FIELDS},
                "offerings": by_course.get(course.id, []),
            }
            for course in courses
        ]

    async def apply_changeset(self, changeset: dict) -> None:
        """Write the staged changeset to the live catalog (approve path).

        ``*_removed`` deactivates rows — history is never hard-deleted.
        """
        courses_by_code = {
            course.course_code: course
            for course in (await self._session.execute(select(Course))).scalars()
        }
        offerings_by_code = {
            offering.offering_code: offering
            for offering in (
                await self._session.execute(select(CourseOffering))
            ).scalars()
        }

        for added in changeset.get("courses_added", []):
            course = Course(
                course_code=added["course_code"],
                title=added["title"],
                category=added.get("category"),
                description=added.get("description"),
                is_accredited=added.get("is_accredited", False),
                source_url=added.get("source_url"),
                is_active=True,
            )
            self._session.add(course)
            await self._session.flush()
            courses_by_code[course.course_code] = course
            for offering in added.get("offerings", []):
                new_offering = self._build_offering(course.id, offering)
                self._session.add(new_offering)
                offerings_by_code[new_offering.offering_code] = new_offering

        for updated in changeset.get("courses_updated", []):
            updated_course = courses_by_code.get(updated["course_code"])
            if updated_course is None:
                continue
            for field, change in updated["changes"].items():
                setattr(updated_course, field, change["to"])

        for entry in changeset.get("courses_removed", []):
            code = _removed_code(entry, "course_code")
            removed_course = courses_by_code.get(code) if code else None
            if removed_course is not None:
                removed_course.is_active = False

        for added in changeset.get("offerings_added", []):
            parent_course = courses_by_code.get(added["course_code"])
            if parent_course is None:
                continue
            new_offering = self._build_offering(parent_course.id, added)
            self._session.add(new_offering)
            offerings_by_code[new_offering.offering_code] = new_offering

        for updated in changeset.get("offerings_updated", []):
            offering = offerings_by_code.get(updated["offering_code"])
            if offering is None:
                continue
            for field, change in updated["changes"].items():
                value = change["to"]
                if field in ("start_date", "finish_date") and isinstance(value, str):
                    value = _date_from_iso(value)
                setattr(offering, field, value)

        for entry in changeset.get("offerings_removed", []):
            code = _removed_code(entry, "offering_code")
            offering = offerings_by_code.get(code) if code else None
            if offering is not None:
                offering.is_active = False
                offering.status = "cancelled"

    @staticmethod
    def _build_offering(course_id: uuid.UUID, payload: dict) -> CourseOffering:
        return CourseOffering(
            course_id=course_id,
            offering_code=payload["offering_code"],
            price=payload.get("price"),
            gst=payload.get("gst"),
            status=payload.get("status", "active"),
            places_available=payload.get("places_available"),
            places_text=payload.get("places_text"),
            location=payload.get("location"),
            start_date=_date_from_iso(payload.get("start_date")),
            finish_date=_date_from_iso(payload.get("finish_date")),
            time_text=payload.get("time_text"),
            session_count=payload.get("session_count"),
            session_hours=payload.get("session_hours"),
            enrollment_url=payload.get("enrollment_url"),
            detail_url=payload.get("detail_url"),
            is_active=True,
        )

    # ── Read API for the catalog endpoints / course picker ──

    async def list_courses(
        self,
        *,
        category: str | None = None,
        search: str | None = None,
        accredited: bool | None = None,
        include_inactive: bool = False,
    ) -> list[Course]:
        query = select(Course).order_by(Course.title)
        if not include_inactive:
            query = query.where(Course.is_active.is_(True))
        if category:
            query = query.where(Course.category == category)
        if accredited is not None:
            query = query.where(Course.is_accredited.is_(accredited))
        if search:
            pattern = f"%{search.lower()}%"
            from sqlalchemy import func, or_

            query = query.where(
                or_(
                    func.lower(Course.title).like(pattern),
                    func.lower(Course.course_code).like(pattern),
                )
            )
        return list((await self._session.execute(query)).scalars().all())

    async def get_course(self, course_id: uuid.UUID) -> Course | None:
        return (
            await self._session.execute(select(Course).where(Course.id == course_id))
        ).scalar_one_or_none()

    async def get_offerings(self, course_id: uuid.UUID) -> list[CourseOffering]:
        query = (
            select(CourseOffering)
            .where(
                CourseOffering.course_id == course_id,
                CourseOffering.is_active.is_(True),
            )
            .order_by(CourseOffering.start_date.asc().nulls_last())
        )
        return list((await self._session.execute(query)).scalars().all())


class ScraperRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self) -> ScraperRun:
        run = ScraperRun(
            status=ScraperRunStatus.running, started_at=dt.datetime.now(dt.UTC)
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def get(self, run_id: uuid.UUID) -> ScraperRun | None:
        return (
            await self._session.execute(
                select(ScraperRun).where(ScraperRun.id == run_id)
            )
        ).scalar_one_or_none()

    async def list_recent(self, *, limit: int = 20) -> list[ScraperRun]:
        query = select(ScraperRun).order_by(ScraperRun.created_at.desc()).limit(limit)
        return list((await self._session.execute(query)).scalars().all())

    async def get_pending(self) -> ScraperRun | None:
        query = (
            select(ScraperRun)
            .where(ScraperRun.status == ScraperRunStatus.pending)
            .order_by(ScraperRun.created_at.desc())
        )
        return (await self._session.execute(query)).scalars().first()

    async def has_open_run(self) -> bool:
        """True while a run is still running or awaiting review."""
        query = select(ScraperRun).where(
            ScraperRun.status.in_(
                [ScraperRunStatus.running, ScraperRunStatus.pending]
            )
        )
        return (await self._session.execute(query)).scalars().first() is not None
