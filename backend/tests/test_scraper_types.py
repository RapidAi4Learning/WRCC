"""Field normalization helpers (pure functions)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.scraper.types import (
    instance_id_from_url,
    is_accredited_code,
    parse_date_range,
    parse_places,
    parse_price,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$185.00", 185.0),
        ("$1,250.50", 1250.5),
        ("Free", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_price(raw: str | None, expected: float | None) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("10", 10), ("4 spaces", 4), ("Fully booked", None), (None, None)],
)
def test_parse_places(raw: str | None, expected: int | None) -> None:
    assert parse_places(raw) == expected


@pytest.mark.parametrize(
    ("raw", "start", "finish"),
    [
        ("24 July 2026", dt.date(2026, 7, 24), dt.date(2026, 7, 24)),
        ("28 - 30 September 2026", dt.date(2026, 9, 28), dt.date(2026, 9, 30)),
        ("30 September - 2 October 2026", dt.date(2026, 9, 30), dt.date(2026, 10, 2)),
        # En-dash variant and whitespace tolerance.
        ("6 – 8 October 2026", dt.date(2026, 10, 6), dt.date(2026, 10, 8)),
        ("TBA", None, None),
        ("", None, None),
        (None, None, None),
        ("32 Nonexistember 2026", None, None),
    ],
)
def test_parse_date_range(
    raw: str | None, start: dt.date | None, finish: dt.date | None
) -> None:
    assert parse_date_range(raw) == (start, finish)


def test_instance_id_from_url() -> None:
    url = "/course-enrol?course_id=106860&course_type=w&instance_id=2392073"
    assert instance_id_from_url(url) == "2392073"
    assert instance_id_from_url("/course-enrol?course_id=1") is None
    assert instance_id_from_url(None) is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("HLTAID011", True),
        ("TLILIC0003", True),
        ("SITHFAB021", True),
        ("HLTAID012OL", True),  # code with suffix still starts with the pattern
        ("yoga-for-beginners", False),
        ("Pilates", False),
    ],
)
def test_is_accredited_code(code: str, expected: bool) -> None:
    assert is_accredited_code(code) is expected
