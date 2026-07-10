"""Course-detail page parser: offering rows + short description.

The aXcelerate-rendered markup is malformed (offering ``<tr>`` rows are emitted
outside the ``<table>`` element), so rows are located by their stable
``instance_*`` cell classes anywhere in the document rather than by table
structure.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.scraper.types import (
    ScrapedOffering,
    instance_id_from_url,
    parse_date_range,
    parse_places,
    parse_price,
)


def _cell_text(row: Tag, css_class: str) -> str | None:
    cell = row.select_one(f"td.{css_class}")
    if cell is None:
        return None
    text = cell.get_text(" ", strip=True)
    return text or None


def parse_course_detail(
    html: str, *, detail_url: str | None = None, base_url: str = ""
) -> tuple[str | None, list[ScrapedOffering]]:
    """Parse a detail page → (short_description, offerings).

    Online-only courses without scheduled rows return an empty offering list;
    ``normalize`` synthesizes their on-demand offering so the distinction stays
    in one place.
    """
    soup = BeautifulSoup(html, "html.parser")

    description_el = soup.select_one("#workshopShortDesc")
    description = description_el.get_text(" ", strip=True) if description_el else None

    offerings: list[ScrapedOffering] = []
    for name_cell in soup.select("td.instance_name"):
        row = name_cell.find_parent("tr")
        if row is None:
            continue

        apply_el = row.select_one("a[href*='instance_id=']")
        apply_href = str(apply_el["href"]) if apply_el else None
        offering_code = instance_id_from_url(apply_href)
        if not offering_code:
            # A row without an instance id cannot be tracked across syncs.
            continue

        enrollment_url = apply_href
        if enrollment_url and enrollment_url.startswith("/") and base_url:
            enrollment_url = base_url.rstrip("/") + enrollment_url

        start_date, finish_date = parse_date_range(_cell_text(row, "instance_date"))
        places_text = _cell_text(row, "instance_vacancy")

        offerings.append(
            ScrapedOffering(
                offering_code=offering_code,
                price=parse_price(_cell_text(row, "instance_cost")),
                places_available=parse_places(places_text),
                places_text=places_text,
                location=_cell_text(row, "instance_location"),
                start_date=start_date,
                finish_date=finish_date,
                time_text=_cell_text(row, "instance_time"),
                enrollment_url=enrollment_url,
                detail_url=detail_url,
            )
        )

    return description, offerings
