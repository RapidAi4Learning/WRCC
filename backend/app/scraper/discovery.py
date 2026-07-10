"""Category-page discovery: extract course cards from the 10 WRCC categories.

``CATEGORY_SEEDS`` is a verified snapshot of the site's category slugs; drift
(a seed page without any course card) is a warning, never fatal.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.scraper.types import ScrapedCourseCard

# Verified against https://wrcc.nsw.edu.au navigation (2026-07-10).
CATEGORY_SEEDS: dict[str, str] = {
    "adult-literacy-and-numeracy": "Adult Literacy and Numeracy",
    "business-and-information-technology-skills": "Business and Information Technology Skills",
    "community-and-health-services": "Community and Health Services",
    "first-aid": "First Aid",
    "fitness": "Fitness",
    "hospitality": "Hospitality",
    "leisure-and-lifestyle": "Leisure and Lifestyle",
    "liquor-and-gaming-skills": "Liquor and Gaming Skills",
    "plant-and-equipment": "Plant and Equipment",
    "work-health-and-safety": "Work Health and Safety",
}


def category_urls(base_url: str) -> dict[str, str]:
    """Map category name → absolute category page URL."""
    base = base_url.rstrip("/")
    return {name: f"{base}/{slug}/" for slug, name in CATEGORY_SEEDS.items()}


def parse_category_page(html: str, *, category: str) -> list[ScrapedCourseCard]:
    """Extract course cards (`.ax-course-list-record`) from a category page.

    A card missing its code or detail link is skipped rather than aborting the
    page — missing DOM fields degrade gracefully.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ScrapedCourseCard] = []

    for record in soup.select(".ax-course-list-record"):
        name_el = record.select_one(".ax-course-name")
        code_el = record.select_one(".ax-course-code")
        description_el = record.select_one(".ax-course-list-description")
        link_el = record.select_one("a.ax-course-detail-link[href]")

        card = ScrapedCourseCard(
            course_code=code_el.get_text(strip=True) if code_el else "",
            title=name_el.get_text(strip=True) if name_el else "",
            category=category,
            description=(
                description_el.get_text(" ", strip=True) if description_el else None
            ),
            detail_url=str(link_el["href"]) if link_el else None,
        )
        if card.is_valid:
            cards.append(card)
    return cards
