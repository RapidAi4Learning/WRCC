import { describe, expect, it } from "vitest";

import {
  buildItems,
  buildSkipSelection,
  changesetTotals,
  countSkipped,
  destructiveWarning,
  fieldLabel,
  formatFieldValue,
  formatRunTiming,
  itemLabel,
  removedCourse,
  removedOffering,
  setSectionSkipped,
  skipKey,
  tallyLabel,
  toggleSkip,
} from "@/lib/syncChangeset";
import type { SyncRun } from "@/types/course";

describe("field rendering", () => {
  it("names columns in the operator's words", () => {
    expect(fieldLabel("places_available")).toBe("Places left");
    expect(fieldLabel("start_date")).toBe("Starts");
  });

  it("falls back to a readable version of an unmapped column", () => {
    expect(fieldLabel("some_new_column")).toBe("some new column");
  });

  it("renders each value in the terms of its own field", () => {
    expect(formatFieldValue("price", 185)).toBe("$185.00");
    expect(formatFieldValue("is_accredited", false)).toBe("Not accredited");
    expect(formatFieldValue("is_active", true)).toBe("Listed");
    expect(formatFieldValue("start_date", "2026-08-07")).toBe("7 Aug 2026");
  });

  it("shows an em dash rather than 'null' for an absent value", () => {
    expect(formatFieldValue("location", null)).toBe("—");
    expect(formatFieldValue("location", "")).toBe("—");
  });

  it("strips the scheme off a URL so the path stays readable", () => {
    expect(formatFieldValue("source_url", "https://www.wrcc.nsw.edu.au/x")).toBe(
      "wrcc.nsw.edu.au/x",
    );
  });

  it("truncates a description instead of flooding the diff", () => {
    const long = "a".repeat(300);
    const rendered = formatFieldValue("description", long);
    expect(rendered.length).toBeLessThan(long.length);
    expect(rendered.endsWith("…")).toBe(true);
  });
});

describe("removal entries", () => {
  it("passes an enriched entry through untouched", () => {
    const entry = {
      course_code: "HLTAID011",
      title: "Provide First Aid",
      category: "First Aid",
      offerings_affected: 3,
    };
    expect(removedCourse(entry)).toBe(entry);
  });

  it("reads a legacy bare code without losing the code itself", () => {
    expect(removedCourse("HLTAID011").course_code).toBe("HLTAID011");
    expect(removedCourse("HLTAID011").title).toBeNull();
    expect(removedOffering("9001").offering_code).toBe("9001");
  });
});

describe("tallies", () => {
  it("counts every section and separates the destructive ones", () => {
    const totals = changesetTotals({
      courses_added: [
        {
          course_code: "A",
          title: "A",
          category: null,
          description: null,
          is_accredited: false,
          source_url: null,
          offerings: [],
        },
      ],
      courses_removed: ["B"],
      offerings_removed: ["1", "2"],
    });

    expect(totals).toEqual({ total: 4, destructive: 3, isEmpty: false });
  });

  it("reports an absent changeset as empty rather than throwing", () => {
    expect(changesetTotals(null).isEmpty).toBe(true);
  });

  it("agrees with the count on singular and plural", () => {
    expect(tallyLabel("courses_added", 1)).toBe("new course");
    expect(tallyLabel("courses_added", 3)).toBe("new courses");
  });
});

describe("destructive warning", () => {
  it("stays silent when nothing is deactivated", () => {
    expect(destructiveWarning(0, 0)).toBeNull();
  });

  it("counts both kinds of removal and says nothing is deleted", () => {
    const warning = destructiveWarning(1, 2);
    expect(warning).toContain("1 course and 2 course dates");
    expect(warning).toContain("Nothing is deleted");
  });
});

describe("run timing", () => {
  const run = (overrides: Partial<SyncRun> = {}): SyncRun => ({
    id: "run-1",
    status: "pending",
    courses_found: 1,
    offerings_found: 1,
    changeset: {},
    error: null,
    started_at: "2026-09-02T01:00:00Z",
    finished_at: "2026-09-02T01:00:38Z",
    reviewed_at: null,
    created_at: "2026-09-02T01:00:00Z",
    ...overrides,
  });

  it("says how stale the changeset is and how long the crawl took", () => {
    const now = Date.parse("2026-09-02T01:15:38Z");
    expect(formatRunTiming(run(), now)).toBe("Crawled 15 min ago · took 38s");
  });

  it("reads as 'just now' for a crawl that has only now landed", () => {
    const now = Date.parse("2026-09-02T01:00:50Z");
    expect(formatRunTiming(run(), now)).toContain("just now");
  });

  it("does not invent a time when the run never recorded one", () => {
    expect(formatRunTiming(run({ finished_at: null }))).toBe("Crawl time unknown");
  });
});

describe("selection", () => {
  const items = [
    { code: "A", courseCode: "A", title: "A", meta: null, changes: null },
    { code: "B", courseCode: "B", title: "B", meta: null, changes: null },
  ];

  it("toggles a single entry on and back off", () => {
    const once = toggleSkip(new Set(), skipKey("courses_added", "A"));
    expect(once.has("courses_added:A")).toBe(true);

    const twice = toggleSkip(once, skipKey("courses_added", "A"));
    expect(twice.size).toBe(0);
  });

  it("never mutates the set it was given", () => {
    const original = new Set<string>();
    toggleSkip(original, "courses_added:A");
    expect(original.size).toBe(0);
  });

  it("skips or restores a whole section at once", () => {
    const skipped = setSectionSkipped(new Set(), "courses_added", items, true);
    expect(countSkipped(skipped, "courses_added", items)).toBe(2);

    const restored = setSectionSkipped(skipped, "courses_added", items, false);
    expect(countSkipped(restored, "courses_added", items)).toBe(0);
  });

  it("keys entries per section so equal codes stay independent", () => {
    const skipped = setSectionSkipped(new Set(), "courses_added", items, true);
    expect(countSkipped(skipped, "offerings_added", items)).toBe(0);
  });

  it("sends no selection at all when nothing was unticked", () => {
    expect(buildSkipSelection(new Set())).toBeUndefined();
  });

  it("groups skipped codes back into the shape the endpoint takes", () => {
    const skipped = new Set([
      "courses_added:A",
      "courses_added:B",
      "offerings_removed:9001",
    ]);

    expect(buildSkipSelection(skipped)).toEqual({
      courses_added: ["A", "B"],
      offerings_removed: ["9001"],
    });
  });

  it("keeps a code containing a colon intact", () => {
    expect(buildSkipSelection(new Set(["courses_added:A:B"]))).toEqual({
      courses_added: ["A:B"],
    });
  });
});

describe("review rows", () => {
  it("keys a course row by its code and names what it is", () => {
    const [item] = buildItems(
      "courses_added",
      {
        courses_added: [
          {
            course_code: "WHS101",
            title: "Work Health & Safety",
            category: "Safety",
            description: null,
            is_accredited: true,
            source_url: null,
            offerings: [{ offering_code: "1" }, { offering_code: "2" }],
          },
        ],
      },
      {},
    );

    expect(item.code).toBe("WHS101");
    expect(item.title).toBe("Work Health & Safety");
    expect(item.meta).toBe("Safety · Accredited · 2 dates");
  });

  it("keys a date row by its offering code, not the course it hangs off", () => {
    const [item] = buildItems(
      "offerings_added",
      {
        offerings_added: [
          {
            offering_code: "9002",
            course_code: "HLTAID011",
            price: 185,
            location: "WRCC Griffith",
            start_date: "2026-08-07",
            finish_date: "2026-08-07",
            places_available: 1,
          },
        ],
      },
      { HLTAID011: "Provide First Aid" },
    );

    expect(item.code).toBe("9002");
    expect(item.courseCode).toBe("HLTAID011");
    expect(item.title).toBe("Provide First Aid");
    expect(item.meta).toBe("7 Aug 2026 · WRCC Griffith · $185.00 · 1 place");
  });

  it("falls back to the old title for a course being renamed", () => {
    const [item] = buildItems(
      "courses_updated",
      {
        courses_updated: [
          {
            course_code: "A",
            changes: { title: { from: "Frst Aid", to: "First Aid" } },
          },
        ],
      },
      {},
    );

    expect(item.title).toBe("Frst Aid");
    expect(item.changes).toEqual({ title: { from: "Frst Aid", to: "First Aid" } });
  });

  it("labels a row by course and title, falling back to the bare code", () => {
    expect(
      itemLabel({
        code: "9002",
        courseCode: "HLTAID011",
        title: "Provide First Aid",
        meta: null,
        changes: null,
      }),
    ).toBe("HLTAID011 — Provide First Aid");

    expect(
      itemLabel({
        code: "9002",
        courseCode: null,
        title: null,
        meta: null,
        changes: null,
      }),
    ).toBe("9002");
  });
});
