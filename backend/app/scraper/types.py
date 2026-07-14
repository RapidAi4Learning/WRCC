"""Shared scraper types and field-normalization helpers.

Kept dependency-free (stdlib only) so parser/discovery unit tests need no
network or database.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")
# National training codes: HLTAID011, TLILIC0003, SITHFAB021… (unit codes use
# 3–10 uppercase letters — e.g. the 7-letter SITHFAB prefix — then 3–5 digits).
_ACCREDITED_CODE_RE = re.compile(r"^[A-Z]{3,10}\d{3,5}")
# A code at the start of a course title, e.g. "HLTAID009 Provide CPR" or the
# suffixed site variant "HLTAID012OL …". Requires a separator after the code so
# a code-only title is left untouched.
_LEADING_CODE_RE = re.compile(r"^[A-Z]{3,10}\d{3,5}[A-Z]{0,4}[\s:–-]+")
# "24 July 2026" or a range "28 - 30 September 2026" /
# "30 September - 2 October 2026" (month optional on the start side).
_DATE_RANGE_RE = re.compile(
    r"^\s*(\d{1,2})(?:\s+([A-Za-z]+))?(?:\s+(\d{4}))?"
    r"\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$"
)
_SINGLE_DATE_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$")

_MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


def parse_price(raw: str | None) -> float | None:
    """'$185.00' → 185.0; returns None when no number is present."""
    if not raw:
        return None
    match = _PRICE_RE.search(raw)
    if match is None:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def parse_places(raw: str | None) -> int | None:
    """First standalone integer in a vacancy cell, e.g. '10' or '4 spaces'."""
    if not raw:
        return None
    match = re.search(r"\b(\d+)\b", raw)
    return int(match.group(1)) if match else None


def _month_number(name: str | None) -> int | None:
    if not name:
        return None
    return _MONTHS.get(name.strip().lower())


def parse_date_range(raw: str | None) -> tuple[dt.date | None, dt.date | None]:
    """Parse the site's date cell into (start_date, finish_date).

    Handles '24 July 2026', '28 - 30 September 2026' and
    '30 September - 2 October 2026'. Unparseable input degrades to (None, None)
    — a missing date never aborts a scrape.
    """
    if not raw:
        return (None, None)
    text = raw.strip()

    single = _SINGLE_DATE_RE.match(text)
    if single:
        month = _month_number(single.group(2))
        if month is None:
            return (None, None)
        try:
            day = dt.date(int(single.group(3)), month, int(single.group(1)))
        except ValueError:
            return (None, None)
        return (day, day)

    ranged = _DATE_RANGE_RE.match(text)
    if ranged:
        start_day, start_month_name, start_year, end_day, end_month_name, end_year = (
            ranged.groups()
        )
        end_month = _month_number(end_month_name)
        start_month = _month_number(start_month_name) or end_month
        year_end = int(end_year)
        year_start = int(start_year) if start_year else year_end
        if end_month is None or start_month is None:
            return (None, None)
        try:
            start = dt.date(year_start, start_month, int(start_day))
            finish = dt.date(year_end, end_month, int(end_day))
        except ValueError:
            return (None, None)
        return (start, finish)

    return (None, None)


def instance_id_from_url(url: str | None) -> str | None:
    """Extract the aXcelerate instance_id from a course-enrol Apply link."""
    if not url:
        return None
    query = parse_qs(urlsplit(url).query)
    values = query.get("instance_id")
    return values[0] if values else None


def course_id_from_url(url: str | None) -> str | None:
    """Extract the course_id from a course-details link."""
    if not url:
        return None
    query = parse_qs(urlsplit(url).query)
    values = query.get("course_id")
    return values[0] if values else None


def is_accredited_code(code: str) -> bool:
    """Derived from the national code pattern (HLTAID011, TLILIC0003, …)."""
    return bool(_ACCREDITED_CODE_RE.match(code.strip()))


def strip_leading_course_code(title: str) -> str:
    """'HLTAID009 Provide CPR' → 'Provide CPR'.

    The site prefixes accredited course names with the national code, which is
    already stored separately as ``course_code``. Falls back to the original
    title when stripping would leave nothing.
    """
    text = title.strip()
    stripped = _LEADING_CODE_RE.sub("", text).strip()
    return stripped or text


@dataclass(slots=True)
class ScrapedCourseCard:
    """One course card on a category page."""

    course_code: str
    title: str
    category: str
    description: str | None = None
    detail_url: str | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.course_code and self.title)


@dataclass(slots=True)
class ScrapedOffering:
    """One scheduled instance row on a course detail page.

    ``offering_code`` is the aXcelerate instance id from the Apply link (or a
    synthetic ``on-demand:<course_id>`` for online-only courses without dates).
    Every other field degrades to ``None`` so a missing DOM cell never aborts
    a whole scrape.
    """

    offering_code: str
    price: float | None = None
    gst: str | None = None
    status: str = "active"
    places_available: int | None = None
    places_text: str | None = None
    location: str | None = None
    start_date: dt.date | None = None
    finish_date: dt.date | None = None
    time_text: str | None = None
    session_count: int | None = None
    session_hours: float | None = None
    enrollment_url: str | None = None
    detail_url: str | None = None


@dataclass(slots=True)
class ScrapedCourseGroup:
    """A course plus its scraped offerings — the unit staged by the sync."""

    course_code: str
    title: str
    category: str | None = None
    description: str | None = None
    is_accredited: bool = False
    source_url: str | None = None
    offerings: list[ScrapedOffering] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
