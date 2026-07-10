"""Pure changeset diff: scraped groups vs live catalog rows.

No DB session, no network — the repository queries the live state and passes
it in as plain dicts, and stores the resulting JSON-serializable changeset on
``scraper_runs.changeset``. Idempotency contract: a re-scrape with no upstream
change yields an empty changeset.

``removed`` always means *deactivate* (soft delete), never a hard delete.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.scraper.types import ScrapedCourseGroup, ScrapedOffering

COURSE_FIELDS: tuple[str, ...] = (
    "title",
    "category",
    "description",
    "is_accredited",
    "source_url",
)

OFFERING_FIELDS: tuple[str, ...] = (
    "price",
    "gst",
    "status",
    "places_available",
    "places_text",
    "location",
    "start_date",
    "finish_date",
    "time_text",
    "session_count",
    "session_hours",
    "enrollment_url",
    "detail_url",
)

_NUMERIC_FIELDS = frozenset({"price", "session_hours"})


def _serialize(value: Any) -> Any:
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _normalize(field: str, value: Any) -> Any:
    """Canonicalize so equal-but-differently-typed values compare equal.

    Live rows come back as Decimal (Numeric columns) and ISO strings may
    appear on either side after JSON round-trips.
    """
    if value is None:
        return None
    if field in _NUMERIC_FIELDS:
        return float(value)
    if field in ("start_date", "finish_date") and isinstance(value, dt.date):
        return value.isoformat()
    return value


def course_payload(group: ScrapedCourseGroup) -> dict:
    return {
        "course_code": group.course_code,
        "title": group.title,
        "category": group.category,
        "description": group.description,
        "is_accredited": group.is_accredited,
        "source_url": group.source_url,
    }


def offering_payload(offering: ScrapedOffering) -> dict:
    payload = {"offering_code": offering.offering_code}
    for field in OFFERING_FIELDS:
        payload[field] = _serialize(getattr(offering, field))
    return payload


def _field_changes(
    fields: tuple[str, ...], live: dict, scraped: dict
) -> dict[str, dict]:
    changes: dict[str, dict] = {}
    for field in fields:
        old = _normalize(field, live.get(field))
        new = _normalize(field, scraped.get(field))
        if old != new:
            changes[field] = {"from": _serialize(live.get(field)), "to": scraped.get(field)}
    return changes


def build_changeset(
    groups: list[ScrapedCourseGroup], live_courses: list[dict]
) -> dict:
    """Classify every scraped course/offering against the live rows.

    ``live_courses``: dicts with COURSE_FIELDS + ``course_code``, ``is_active``
    and ``offerings`` (dicts with OFFERING_FIELDS + ``offering_code``,
    ``is_active``).
    """
    live_by_code = {c["course_code"]: c for c in live_courses}
    live_offerings: dict[str, dict] = {}
    offering_course: dict[str, str] = {}
    for course in live_courses:
        for offering in course.get("offerings", []):
            live_offerings[offering["offering_code"]] = offering
            offering_course[offering["offering_code"]] = course["course_code"]

    changeset: dict = {
        "courses_added": [],
        "courses_updated": [],
        "courses_removed": [],
        "offerings_added": [],
        "offerings_updated": [],
        "offerings_removed": [],
    }

    seen_courses: set[str] = set()
    seen_offerings: set[str] = set()

    for group in groups:
        seen_courses.add(group.course_code)
        scraped_course = course_payload(group)
        live = live_by_code.get(group.course_code)

        if live is None:
            changeset["courses_added"].append(
                {**scraped_course, "offerings": [offering_payload(o) for o in group.offerings]}
            )
            seen_offerings.update(o.offering_code for o in group.offerings)
            continue

        changes = _field_changes(COURSE_FIELDS, live, scraped_course)
        if not live.get("is_active", True):
            changes["is_active"] = {"from": False, "to": True}
        if changes:
            changeset["courses_updated"].append(
                {"course_code": group.course_code, "changes": changes}
            )

        for offering in group.offerings:
            seen_offerings.add(offering.offering_code)
            scraped_offering = offering_payload(offering)
            live_offering = live_offerings.get(offering.offering_code)
            if live_offering is None:
                changeset["offerings_added"].append(
                    {"course_code": group.course_code, **scraped_offering}
                )
                continue
            offering_changes = _field_changes(
                OFFERING_FIELDS, live_offering, scraped_offering
            )
            if not live_offering.get("is_active", True):
                offering_changes["is_active"] = {"from": False, "to": True}
            if offering_changes:
                changeset["offerings_updated"].append(
                    {
                        "offering_code": offering.offering_code,
                        "course_code": group.course_code,
                        "changes": offering_changes,
                    }
                )

    for code, course in live_by_code.items():
        if code not in seen_courses and course.get("is_active", True):
            changeset["courses_removed"].append(code)
    for code, offering in live_offerings.items():
        if code not in seen_offerings and offering.get("is_active", True):
            changeset["offerings_removed"].append(code)

    changeset["summary"] = {key: len(value) for key, value in changeset.items()}
    return changeset


def is_empty_changeset(changeset: dict) -> bool:
    return not any(
        changeset.get(key)
        for key in (
            "courses_added",
            "courses_updated",
            "courses_removed",
            "offerings_added",
            "offerings_updated",
            "offerings_removed",
        )
    )
