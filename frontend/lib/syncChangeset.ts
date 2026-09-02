// Reading a staged sync changeset the way a reviewer needs it.
//
// The backend stages a machine-shaped diff: snake_case field names, ISO dates,
// raw decimals and codes. None of that is reviewable on sight — approving a
// sync deactivates real courses on a live site — so this module turns the diff
// into the words and numbers an operator actually judges: what the field is
// called, what it used to say, what it will say, and how much of the change is
// destructive.
//
// Everything here is pure, so the panel stays a rendering concern.

import type {
  Changeset,
  RemovalEntry,
  StagedCourseRemoval,
  StagedOfferingRemoval,
  SyncRun,
} from "@/types/course";

export type SectionKey =
  | "courses_added"
  | "courses_updated"
  | "courses_removed"
  | "offerings_added"
  | "offerings_updated"
  | "offerings_removed";

// Destructive first: what disappears is what needs the closest look.
export const SECTION_KEYS: readonly SectionKey[] = [
  "courses_removed",
  "offerings_removed",
  "courses_added",
  "offerings_added",
  "courses_updated",
  "offerings_updated",
] as const;

export type ChangeTone = "add" | "update" | "remove";

export const SECTION_TONES: Record<SectionKey, ChangeTone> = {
  courses_added: "add",
  offerings_added: "add",
  courses_updated: "update",
  offerings_updated: "update",
  courses_removed: "remove",
  offerings_removed: "remove",
};

export const SECTION_TITLES: Record<SectionKey, string> = {
  courses_added: "New courses",
  courses_updated: "Updated courses",
  courses_removed: "Courses to deactivate",
  offerings_added: "New course dates",
  offerings_updated: "Updated course dates",
  offerings_removed: "Course dates to cancel",
};

// Singular / plural, phrased so a tally reads as a sentence: "3 new courses".
const TALLY_WORDS: Record<SectionKey, [string, string]> = {
  courses_added: ["new course", "new courses"],
  courses_updated: ["course updated", "courses updated"],
  courses_removed: ["course to deactivate", "courses to deactivate"],
  offerings_added: ["new date", "new dates"],
  offerings_updated: ["date updated", "dates updated"],
  offerings_removed: ["date to cancel", "dates to cancel"],
};

const DESTRUCTIVE_KEYS: readonly SectionKey[] = [
  "courses_removed",
  "offerings_removed",
];

/** Human name for a diffed column. Anything unmapped degrades to its own name. */
const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  category: "Category",
  description: "Description",
  is_accredited: "Accreditation",
  source_url: "Course page",
  is_active: "Listing",
  price: "Price",
  gst: "GST",
  status: "Status",
  places_available: "Places left",
  places_text: "Places",
  location: "Location",
  start_date: "Starts",
  finish_date: "Finishes",
  time_text: "Time",
  session_count: "Sessions",
  session_hours: "Hours",
  enrollment_url: "Enrolment link",
  detail_url: "Detail page",
};

const MONEY_FIELDS = new Set(["price", "gst"]);
const DATE_FIELDS = new Set(["start_date", "finish_date"]);
const URL_FIELDS = new Set(["source_url", "enrollment_url", "detail_url"]);

const EMPTY = "—";
const MAX_TEXT = 140;
const MAX_URL = 44;

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field.replace(/_/g, " ");
}

export function formatMoney(value: number | null | undefined): string {
  return value === null || value === undefined ? EMPTY : `$${value.toFixed(2)}`;
}

/** ISO date to "7 Aug 2026", parsed as a plain date so no timezone shifts it. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const parsed = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** Render one side of a diff in the terms of the field it belongs to. */
export function formatFieldValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  if (field === "is_accredited") return value ? "Accredited" : "Not accredited";
  if (field === "is_active") return value ? "Listed" : "Hidden";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (MONEY_FIELDS.has(field)) return formatMoney(Number(value));
  if (DATE_FIELDS.has(field)) return formatDate(String(value));
  if (URL_FIELDS.has(field)) {
    return truncate(String(value).replace(/^https?:\/\/(www\.)?/, ""), MAX_URL);
  }
  return truncate(String(value), MAX_TEXT);
}

// ── Removal entries ──
//
// Both accessors accept the legacy bare-code shape: a run staged before
// removals carried context can still be sitting in review.

export function removedCourse(
  entry: RemovalEntry<StagedCourseRemoval>,
): StagedCourseRemoval {
  if (typeof entry !== "string") return entry;
  return {
    course_code: entry,
    title: null,
    category: null,
    offerings_affected: 0,
  };
}

export function removedOffering(
  entry: RemovalEntry<StagedOfferingRemoval>,
): StagedOfferingRemoval {
  if (typeof entry !== "string") return entry;
  return {
    offering_code: entry,
    course_code: null,
    start_date: null,
    location: null,
    price: null,
  };
}

// ── Tallies ──

export function sectionCount(
  changeset: Changeset | null,
  key: SectionKey,
): number {
  return changeset?.[key]?.length ?? 0;
}

export function tallyLabel(key: SectionKey, count: number): string {
  const [singular, plural] = TALLY_WORDS[key];
  return count === 1 ? singular : plural;
}

export interface ChangesetTotals {
  total: number;
  destructive: number;
  isEmpty: boolean;
}

export function changesetTotals(changeset: Changeset | null): ChangesetTotals {
  const total = SECTION_KEYS.reduce(
    (sum, key) => sum + sectionCount(changeset, key),
    0,
  );
  const destructive = DESTRUCTIVE_KEYS.reduce(
    (sum, key) => sum + sectionCount(changeset, key),
    0,
  );
  return { total, destructive, isEmpty: total === 0 };
}

/** The warning above the actions, or null when nothing goes dark. */
export function destructiveWarning(changeset: Changeset | null): string | null {
  const courses = sectionCount(changeset, "courses_removed");
  const dates = sectionCount(changeset, "offerings_removed");
  if (courses === 0 && dates === 0) return null;

  const parts: string[] = [];
  if (courses > 0) {
    parts.push(`${courses} ${courses === 1 ? "course" : "courses"}`);
  }
  if (dates > 0) {
    parts.push(`${dates} ${dates === 1 ? "course date" : "course dates"}`);
  }
  return (
    `${parts.join(" and ")} will stop showing in this app. Nothing is deleted — ` +
    "approving hides them, and a later sync brings them back if they return upstream."
  );
}

// ── Run timing ──

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

function relative(from: Date, now: number): string {
  const elapsed = now - from.getTime();
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.round(elapsed / MINUTE)} min ago`;
  if (elapsed < 24 * HOUR) {
    const hours = Math.round(elapsed / HOUR);
    return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  }
  return `on ${from.toLocaleDateString("en-AU", { day: "numeric", month: "short" })}`;
}

/**
 * "Crawled 4 min ago · took 38s" — how fresh the changeset is, which is what
 * decides whether it is still worth approving at all.
 */
export function formatRunTiming(run: SyncRun, now: number = Date.now()): string {
  const finished = run.finished_at ? new Date(run.finished_at) : null;
  if (!finished || Number.isNaN(finished.getTime())) return "Crawl time unknown";

  const parts = [`Crawled ${relative(finished, now)}`];
  const started = run.started_at ? new Date(run.started_at) : null;
  if (started && !Number.isNaN(started.getTime())) {
    const seconds = Math.max(
      0,
      Math.round((finished.getTime() - started.getTime()) / SECOND),
    );
    parts.push(
      seconds >= 60 ? `took ${Math.round(seconds / 60)} min` : `took ${seconds}s`,
    );
  }
  return parts.join(" · ");
}
