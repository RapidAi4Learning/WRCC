"""Discovery + parser against captured WRCC fixtures (no network)."""

from __future__ import annotations

import datetime as dt

from app.scraper.discovery import CATEGORY_SEEDS, category_urls, parse_category_page
from app.scraper.parser import parse_course_detail
from tests.conftest import FIXTURES

WRCC = FIXTURES / "wrcc"


def _read(name: str) -> str:
    return (WRCC / name).read_text(encoding="utf-8")


def test_category_seeds_cover_the_ten_site_categories() -> None:
    assert len(CATEGORY_SEEDS) == 10
    urls = category_urls("https://wrcc.nsw.edu.au")
    assert urls["First Aid"] == "https://wrcc.nsw.edu.au/first-aid/"


def test_parse_first_aid_category_extracts_cards() -> None:
    cards = parse_category_page(_read("category_first_aid.html"), category="First Aid")

    assert len(cards) >= 3
    by_code = {card.course_code: card for card in cards}
    assert "HLTAID011" in by_code
    first_aid = by_code["HLTAID011"]
    assert first_aid.title.startswith("HLTAID011 Provide First Aid")
    assert first_aid.category == "First Aid"
    assert first_aid.description
    assert "course-details/?course_id=106860" in (first_aid.detail_url or "")


def test_parse_plant_category_extracts_forklift() -> None:
    cards = parse_category_page(
        _read("category_plant_and_equipment.html"), category="Plant and Equipment"
    )
    codes = {card.course_code for card in cards}
    assert "TLILIC0003" in codes


def test_parse_category_tolerates_unrelated_html() -> None:
    assert parse_category_page("<html><body><p>nothing</p></body></html>", category="X") == []


def test_parse_first_aid_detail_offerings() -> None:
    description, offerings = parse_course_detail(
        _read("detail_106860.html"),
        detail_url="https://wrcc.nsw.edu.au/course-details/?course_id=106860&course_type=w",
        base_url="https://wrcc.nsw.edu.au",
    )

    assert description and "first aid" in description.lower()
    assert len(offerings) >= 10
    codes = {offering.offering_code for offering in offerings}
    assert "2392073" in codes

    first = next(o for o in offerings if o.offering_code == "2392073")
    assert first.price == 185.0
    assert first.location == "WRCC Deniliquin"
    assert first.start_date == dt.date(2026, 7, 24)
    assert first.finish_date == dt.date(2026, 7, 24)
    assert first.places_available == 10
    assert first.time_text and "09:00" in first.time_text
    assert first.enrollment_url == (
        "https://wrcc.nsw.edu.au/course-enrol?course_id=106860&course_type=w"
        "&instance_id=2392073"
    )


def test_parse_forklift_detail_multi_day_ranges() -> None:
    _description, offerings = parse_course_detail(
        _read("detail_74271.html"), base_url="https://wrcc.nsw.edu.au"
    )

    assert len(offerings) >= 10
    assert all(o.price == 780.0 for o in offerings)
    # Every forklift offering is a multi-day range.
    ranged = [o for o in offerings if o.start_date and o.finish_date]
    assert ranged
    assert all(o.finish_date > o.start_date for o in ranged)


def test_parse_detail_without_table_returns_no_offerings() -> None:
    description, offerings = parse_course_detail(
        "<html><body><h1>Online course</h1>"
        "<div id='workshopShortDesc'>Learn online.</div></body></html>"
    )
    assert description == "Learn online."
    assert offerings == []
