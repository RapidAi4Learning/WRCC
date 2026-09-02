"""Partial approval: apply part of a staged changeset, skip the rest.

A reviewer who can only take a changeset whole has no real veto — one wrong
price in a 200-row scrape forces them to reject the other 199 good changes and
re-run the crawl. So approve accepts a set of entry codes to *skip*, and this
module filters the run's own stored changeset down to what was kept.

The client sends codes, never rows: the changeset that gets applied is always
the one the server staged, so an edited request can subtract from the approval
but never smuggle anything into the catalog.

Skipping is "not now", not "never". The live rows stay as they are, so the next
crawl sees the same upstream difference and stages it again.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# The field that identifies an entry within each section of a changeset.
SECTION_CODES: dict[str, str] = {
    "courses_added": "course_code",
    "courses_updated": "course_code",
    "courses_removed": "course_code",
    "offerings_added": "offering_code",
    "offerings_updated": "offering_code",
    "offerings_removed": "offering_code",
}


def entry_code(section: str, entry: Any) -> str | None:
    """The code an entry is selected by, or None if it has none to offer."""
    if isinstance(entry, str):
        # Removals staged before they carried context are bare code strings.
        return entry
    if isinstance(entry, dict):
        code = entry.get(SECTION_CODES[section])
        return code if isinstance(code, str) else None
    return None


def filter_changeset(
    changeset: Mapping[str, Any], skipped: Mapping[str, Iterable[str]] | None
) -> dict:
    """Return a new changeset holding only the entries that were kept.

    Unknown codes are ignored rather than rejected: they can only ever remove
    something from the approval, and a stale tab is not worth failing over.
    """
    if not skipped:
        return dict(changeset)

    filtered: dict[str, Any] = {}
    for section in SECTION_CODES:
        skip = set(skipped.get(section) or ())
        filtered[section] = [
            entry
            for entry in changeset.get(section, [])
            if entry_code(section, entry) not in skip
        ]
    filtered["summary"] = {
        section: len(filtered[section]) for section in SECTION_CODES
    }
    return filtered


def count_entries(changeset: Mapping[str, Any]) -> int:
    return sum(len(changeset.get(section, [])) for section in SECTION_CODES)
