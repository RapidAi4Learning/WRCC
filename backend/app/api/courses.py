"""Catalog + sync HITL endpoints (plan §7). All routes require a session."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.auth.dependencies import get_current_user
from app.db.base import get_session
from app.db.models import Course, CourseOffering, ScraperRun, User
from app.scraper.repository import CatalogRepository, ScraperRunRepository
from app.scraper.service import SyncConflictError, get_sync_service
from app.services.courses import (
    CourseSyncReviewService,
    InvalidRunTransitionError,
    RunNotFoundError,
)

router = APIRouter(
    prefix="/api/courses", tags=["courses"], dependencies=[Depends(get_current_user)]
)


class OfferingOut(BaseModel):
    id: str
    offering_code: str
    price: float | None
    status: str
    places_available: int | None
    places_text: str | None
    location: str | None
    start_date: dt.date | None
    finish_date: dt.date | None
    time_text: str | None
    enrollment_url: str | None


class CourseOut(BaseModel):
    id: str
    course_code: str
    title: str
    category: str | None
    description: str | None
    is_accredited: bool
    source_url: str | None
    is_active: bool


class CourseDetailOut(CourseOut):
    offerings: list[OfferingOut]


class SyncRunOut(BaseModel):
    id: str
    status: str
    courses_found: int
    offerings_found: int
    changeset: dict | None
    error: str | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    reviewed_at: dt.datetime | None
    created_at: dt.datetime


class RejectRequest(BaseModel):
    reason: str | None = None


def _course_out(course: Course) -> CourseOut:
    return CourseOut(
        id=str(course.id),
        course_code=course.course_code,
        title=course.title,
        category=course.category,
        description=course.description,
        is_accredited=course.is_accredited,
        source_url=course.source_url,
        is_active=course.is_active,
    )


def _offering_out(offering: CourseOffering) -> OfferingOut:
    return OfferingOut(
        id=str(offering.id),
        offering_code=offering.offering_code,
        price=float(offering.price) if offering.price is not None else None,
        status=offering.status,
        places_available=offering.places_available,
        places_text=offering.places_text,
        location=offering.location,
        start_date=offering.start_date,
        finish_date=offering.finish_date,
        time_text=offering.time_text,
        enrollment_url=offering.enrollment_url,
    )


def _run_out(run: ScraperRun) -> SyncRunOut:
    return SyncRunOut(
        id=str(run.id),
        status=run.status.value,
        courses_found=run.courses_found,
        offerings_found=run.offerings_found,
        changeset=run.changeset,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        reviewed_at=run.reviewed_at,
        created_at=run.created_at,
    )


# ── Sync HITL (declared before /{course_id} so 'sync' never matches it) ──


@router.post("/sync", response_model=SyncRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_sync(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SyncRunOut:
    service = get_sync_service()
    try:
        run = await service.start_sync(session)
    except SyncConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    record_audit(
        session,
        actor_id=user.id,
        action="catalog_sync_started",
        entity_type="scraper_run",
        entity_id=run.id,
    )
    return _run_out(run)


@router.get("/sync", response_model=list[SyncRunOut])
async def list_sync_runs(
    session: AsyncSession = Depends(get_session),
) -> list[SyncRunOut]:
    runs = await ScraperRunRepository(session).list_recent()
    return [_run_out(run) for run in runs]


@router.get("/sync/{run_id}", response_model=SyncRunOut)
async def get_sync_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> SyncRunOut:
    run = await ScraperRunRepository(session).get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return _run_out(run)


@router.post("/sync/{run_id}/approve", response_model=SyncRunOut)
async def approve_sync_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SyncRunOut:
    try:
        run = await CourseSyncReviewService(session).approve(run_id, actor_id=user.id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _run_out(run)


@router.post("/sync/{run_id}/reject", response_model=SyncRunOut)
async def reject_sync_run(
    run_id: uuid.UUID,
    body: RejectRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SyncRunOut:
    try:
        run = await CourseSyncReviewService(session).reject(
            run_id, actor_id=user.id, reason=body.reason if body else None
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _run_out(run)


# ── Catalog reads ──


@router.get("", response_model=list[CourseOut])
async def list_courses(
    category: str | None = None,
    search: str | None = None,
    accredited: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[CourseOut]:
    courses = await CatalogRepository(session).list_courses(
        category=category, search=search, accredited=accredited
    )
    return [_course_out(course) for course in courses]


@router.get("/{course_id}", response_model=CourseDetailOut)
async def get_course(
    course_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> CourseDetailOut:
    repo = CatalogRepository(session)
    course = await repo.get_course(course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found."
        )
    offerings = await repo.get_offerings(course_id)
    return CourseDetailOut(
        **_course_out(course).model_dump(),
        offerings=[_offering_out(offering) for offering in offerings],
    )
