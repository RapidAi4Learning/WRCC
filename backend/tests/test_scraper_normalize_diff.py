"""Normalization grouping + pure changeset diff."""

from __future__ import annotations

import datetime as dt

from app.scraper.diff import build_changeset, is_empty_changeset, offering_payload
from app.scraper.normalize import ON_DEMAND_PREFIX, build_course_groups
from app.scraper.types import ScrapedCourseCard, ScrapedCourseGroup, ScrapedOffering


def _card(code: str = "HLTAID011", category: str = "First Aid") -> ScrapedCourseCard:
    return ScrapedCourseCard(
        course_code=code,
        title=f"{code} Course",
        category=category,
        description="Card description",
        detail_url="https://wrcc.nsw.edu.au/course-details/?course_id=1&course_type=w",
    )


def _offering(code: str = "111", **overrides) -> ScrapedOffering:
    defaults = dict(
        offering_code=code,
        price=185.0,
        location="WRCC Griffith",
        start_date=dt.date(2026, 8, 7),
        finish_date=dt.date(2026, 8, 7),
        places_available=5,
    )
    defaults.update(overrides)
    return ScrapedOffering(**defaults)


# ── normalize ──


def test_groups_dedup_offerings_and_prefer_detail_description() -> None:
    groups = build_course_groups(
        [
            (_card(), "Detail description", [_offering("111"), _offering("222")]),
            # Same course under a second category: offerings must not duplicate.
            (_card(category="Fitness"), "Detail description", [_offering("111")]),
        ]
    )
    assert len(groups) == 1
    group = groups[0]
    assert group.description == "Detail description"
    assert [o.offering_code for o in group.offerings] == ["111", "222"]
    assert group.is_accredited is True
    assert any("Fitness" in warning for warning in group.warnings)


def test_group_without_offerings_gets_synthetic_on_demand() -> None:
    card = ScrapedCourseCard(
        course_code="online-only",
        title="Online Only",
        category="Business",
        detail_url="https://wrcc.nsw.edu.au/course-details/?course_id=999&course_type=w",
    )
    groups = build_course_groups([(card, "Desc", [])])
    assert len(groups[0].offerings) == 1
    assert groups[0].offerings[0].offering_code == f"{ON_DEMAND_PREFIX}999"
    assert groups[0].is_accredited is False


# ── diff ──


def _group(**overrides) -> ScrapedCourseGroup:
    defaults = dict(
        course_code="HLTAID011",
        title="HLTAID011 Course",
        category="First Aid",
        description="Detail description",
        is_accredited=True,
        source_url="https://wrcc.nsw.edu.au/course-details/?course_id=1",
        offerings=[_offering("111")],
    )
    defaults.update(overrides)
    return ScrapedCourseGroup(**defaults)


def _live_course(**overrides) -> dict:
    course = {
        "course_code": "HLTAID011",
        "title": "HLTAID011 Course",
        "category": "First Aid",
        "description": "Detail description",
        "is_accredited": True,
        "source_url": "https://wrcc.nsw.edu.au/course-details/?course_id=1",
        "is_active": True,
        "offerings": [
            {"offering_code": "111", "is_active": True, **offering_payload(_offering("111"))}
        ],
    }
    course.update(overrides)
    return course


def test_new_course_is_added_with_offerings() -> None:
    changeset = build_changeset([_group()], [])
    assert changeset["summary"]["courses_added"] == 1
    added = changeset["courses_added"][0]
    assert added["course_code"] == "HLTAID011"
    assert added["offerings"][0]["offering_code"] == "111"
    # Dates serialize to ISO strings so the changeset is JSON-storable.
    assert added["offerings"][0]["start_date"] == "2026-08-07"


def test_identical_rescrape_is_empty_changeset() -> None:
    changeset = build_changeset([_group()], [_live_course()])
    assert is_empty_changeset(changeset)


def test_changed_price_and_new_offering_are_classified() -> None:
    group = _group(offerings=[_offering("111", price=195.0), _offering("222")])
    changeset = build_changeset([group], [_live_course()])

    assert changeset["summary"]["offerings_updated"] == 1
    update = changeset["offerings_updated"][0]
    assert update["offering_code"] == "111"
    assert update["changes"]["price"] == {"from": 185.0, "to": 195.0}
    assert changeset["summary"]["offerings_added"] == 1


def test_missing_course_and_offering_are_removed_softly() -> None:
    changeset = build_changeset([], [_live_course()])
    assert changeset["courses_removed"] == ["HLTAID011"]
    assert changeset["offerings_removed"] == ["111"]


def test_inactive_live_rows_do_not_re_remove() -> None:
    live = _live_course(is_active=False)
    live["offerings"][0]["is_active"] = False
    changeset = build_changeset([], [live])
    assert is_empty_changeset(changeset)


def test_reappearing_course_is_reactivated() -> None:
    live = _live_course(is_active=False)
    live["offerings"][0]["is_active"] = False
    changeset = build_changeset([_group()], [live])
    course_changes = changeset["courses_updated"][0]["changes"]
    assert course_changes["is_active"] == {"from": False, "to": True}
    offering_changes = changeset["offerings_updated"][0]["changes"]
    assert offering_changes["is_active"] == {"from": False, "to": True}
