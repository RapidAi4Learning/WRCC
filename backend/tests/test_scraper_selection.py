"""Filtering a staged changeset down to what the reviewer kept."""

from __future__ import annotations

from app.scraper.selection import count_entries, entry_code, filter_changeset


def _changeset() -> dict:
    return {
        "courses_added": [{"course_code": "A", "title": "A"}],
        "courses_updated": [{"course_code": "B", "changes": {}}],
        "courses_removed": [
            {"course_code": "C", "title": "C", "category": None, "offerings_affected": 0}
        ],
        "offerings_added": [{"offering_code": "1", "course_code": "A"}],
        "offerings_updated": [{"offering_code": "2", "course_code": "B", "changes": {}}],
        "offerings_removed": ["3"],
        "summary": {
            "courses_added": 1,
            "courses_updated": 1,
            "courses_removed": 1,
            "offerings_added": 1,
            "offerings_updated": 1,
            "offerings_removed": 1,
        },
    }


def test_no_selection_leaves_the_changeset_whole() -> None:
    changeset = _changeset()
    assert filter_changeset(changeset, None) == changeset
    assert filter_changeset(changeset, {}) == changeset


def test_skipped_entries_are_dropped_from_their_own_section() -> None:
    filtered = filter_changeset(
        _changeset(), {"courses_added": ["A"], "offerings_updated": ["2"]}
    )

    assert filtered["courses_added"] == []
    assert filtered["offerings_updated"] == []
    # Every other section is untouched.
    assert filtered["courses_updated"][0]["course_code"] == "B"
    assert filtered["offerings_added"][0]["offering_code"] == "1"


def test_a_code_only_skips_within_its_own_section() -> None:
    """Course "A" and offering "A" would collide if codes were global."""
    changeset = {
        "courses_added": [{"course_code": "A"}],
        "offerings_added": [{"offering_code": "A", "course_code": "Z"}],
    }
    filtered = filter_changeset(changeset, {"courses_added": ["A"]})

    assert filtered["courses_added"] == []
    assert len(filtered["offerings_added"]) == 1


def test_summary_is_recounted_to_match_what_will_be_applied() -> None:
    filtered = filter_changeset(_changeset(), {"courses_removed": ["C"]})

    assert filtered["summary"]["courses_removed"] == 0
    assert filtered["summary"]["courses_added"] == 1
    assert count_entries(filtered) == 5


def test_legacy_bare_code_removals_can_still_be_skipped() -> None:
    filtered = filter_changeset(
        {"courses_removed": ["OLD101", "OLD102"]}, {"courses_removed": ["OLD101"]}
    )

    assert filtered["courses_removed"] == ["OLD102"]


def test_unknown_codes_are_ignored() -> None:
    filtered = filter_changeset(_changeset(), {"courses_added": ["NOPE"]})

    assert filtered["courses_added"][0]["course_code"] == "A"


def test_skipping_everything_yields_an_empty_apply() -> None:
    changeset = _changeset()
    filtered = filter_changeset(
        changeset,
        {
            "courses_added": ["A"],
            "courses_updated": ["B"],
            "courses_removed": ["C"],
            "offerings_added": ["1"],
            "offerings_updated": ["2"],
            "offerings_removed": ["3"],
        },
    )

    assert count_entries(filtered) == 0


def test_entry_code_reads_both_entry_shapes() -> None:
    assert entry_code("courses_removed", "OLD101") == "OLD101"
    assert entry_code("courses_removed", {"course_code": "A"}) == "A"
    assert entry_code("offerings_added", {"course_code": "A"}) is None
