"""Normalization: cards + parsed details → deduplicated ScrapedCourseGroups."""

from __future__ import annotations

from app.scraper.types import (
    ScrapedCourseCard,
    ScrapedCourseGroup,
    ScrapedOffering,
    course_id_from_url,
    is_accredited_code,
)

ON_DEMAND_PREFIX = "on-demand:"


def build_course_groups(
    entries: list[tuple[ScrapedCourseCard, str | None, list[ScrapedOffering]]],
) -> list[ScrapedCourseGroup]:
    """Group (card, detail_description, offerings) tuples by course_code.

    - Offerings are deduplicated by ``offering_code`` across the whole crawl.
    - A course whose detail page has no scheduled rows gets one synthetic
      ``on-demand`` offering so it remains selectable for content generation.
    - ``is_accredited`` derives from the national-code pattern.
    """
    groups: dict[str, ScrapedCourseGroup] = {}
    seen_offering_codes: set[str] = set()

    for card, detail_description, offerings in entries:
        group = groups.get(card.course_code)
        if group is None:
            group = ScrapedCourseGroup(
                course_code=card.course_code,
                title=card.title,
                category=card.category,
                description=detail_description or card.description,
                is_accredited=is_accredited_code(card.course_code),
                source_url=card.detail_url,
            )
            groups[card.course_code] = group
        elif card.category and group.category and card.category != group.category:
            # Same course listed under two categories: keep the first, note it.
            group.warnings.append(
                f"also listed under category '{card.category}'"
            )

        for offering in offerings:
            if offering.offering_code in seen_offering_codes:
                continue
            seen_offering_codes.add(offering.offering_code)
            group.offerings.append(offering)

    for group in groups.values():
        if not group.offerings:
            course_id = course_id_from_url(group.source_url) or group.course_code
            code = f"{ON_DEMAND_PREFIX}{course_id}"
            if code not in seen_offering_codes:
                seen_offering_codes.add(code)
                group.offerings.append(
                    ScrapedOffering(
                        offering_code=code,
                        places_text="On demand",
                        detail_url=group.source_url,
                    )
                )
                group.warnings.append("no scheduled dates — synthetic on-demand offering")

    return list(groups.values())
