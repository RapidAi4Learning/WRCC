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
  ChangeSelection,
  ChangesetSection,
  FieldChange,
  RemovalEntry,
  StagedCourseRemoval,
  StagedOffering,
  StagedOfferingRemoval,
  SyncRun,
} from "@/types/course";

export type SectionKey = ChangesetSection;

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

/**
 * The warning above the actions, or null when nothing goes dark.
 *
 * Takes counts rather than the changeset because what matters is what is still
 * ticked: untick every deactivation and the warning has to go quiet.
 */
export function destructiveWarning(
  courses: number,
  dates: number,
): string | null {
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

// ── Review rows ──
//
// Every section renders the same shape — tick box, course, one line of context
// or a field diff — so the rows are built here as data and the panel stays a
// single renderer instead of six near-identical ones.

export interface ReviewItem {
  /** The code the server filters on when this entry is skipped. */
  code: string;
  /** The course this touches, as shown to the operator. */
  courseCode: string | null;
  title: string | null;
  meta: string | null;
  changes: Record<string, FieldChange> | null;
}

function metaLine(parts: Array<string | null | undefined>): string | null {
  const line = parts.filter((part): part is string => Boolean(part)).join(" · ");
  return line || null;
}

function plural(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

function offeringMeta(offering: StagedOffering): string | null {
  const start = formatDate(offering.start_date);
  const finish = offering.finish_date;
  const dates =
    finish && finish !== offering.start_date
      ? `${start} → ${formatDate(finish)}`
      : start;
  return metaLine([
    offering.start_date ? dates : "On demand",
    offering.location,
    offering.price === null || offering.price === undefined
      ? null
      : formatMoney(offering.price),
    offering.places_available === null || offering.places_available === undefined
      ? null
      : plural(offering.places_available, "place"),
  ]);
}

export function buildItems(
  key: SectionKey,
  changeset: Changeset,
  courseTitles: Record<string, string>,
): ReviewItem[] {
  const nameOf = (code: string | null | undefined) =>
    code ? courseTitles[code] ?? null : null;

  switch (key) {
    case "courses_added":
      return (changeset.courses_added ?? []).map((course) => ({
        code: course.course_code,
        courseCode: course.course_code,
        title: course.title,
        meta: metaLine([
          course.category,
          course.is_accredited ? "Accredited" : null,
          plural(course.offerings.length, "date"),
        ]),
        changes: null,
      }));

    case "courses_updated":
      return (changeset.courses_updated ?? []).map((update) => ({
        code: update.course_code,
        courseCode: update.course_code,
        // A renamed course has no live title under the new name yet, so the
        // old one from the diff is the honest label.
        title:
          nameOf(update.course_code) ??
          (typeof update.changes.title?.from === "string"
            ? update.changes.title.from
            : null),
        meta: null,
        changes: update.changes,
      }));

    case "courses_removed":
      return (changeset.courses_removed ?? []).map((entry) => {
        const course = removedCourse(entry);
        return {
          code: course.course_code,
          courseCode: course.course_code,
          title: course.title ?? nameOf(course.course_code),
          meta: metaLine([
            course.category,
            course.offerings_affected > 0
              ? `${plural(course.offerings_affected, "scheduled date")} go with it`
              : "no scheduled dates",
          ]),
          changes: null,
        };
      });

    case "offerings_added":
      return (changeset.offerings_added ?? []).map((offering) => ({
        code: offering.offering_code,
        courseCode: offering.course_code ?? null,
        title: nameOf(offering.course_code),
        meta: offeringMeta(offering),
        changes: null,
      }));

    case "offerings_updated":
      return (changeset.offerings_updated ?? []).map((update) => ({
        code: update.offering_code,
        courseCode: update.course_code,
        title: nameOf(update.course_code),
        meta: null,
        changes: update.changes,
      }));

    case "offerings_removed":
      return (changeset.offerings_removed ?? []).map((entry) => {
        const offering = removedOffering(entry);
        return {
          code: offering.offering_code,
          courseCode: offering.course_code,
          title: nameOf(offering.course_code),
          meta: metaLine([
            offering.start_date ? formatDate(offering.start_date) : "On demand",
            offering.location,
            offering.price === null ? null : formatMoney(offering.price),
          ]),
          changes: null,
        };
      });
  }
}

/** How a row names itself to a screen reader, and in the skip summary. */
export function itemLabel(item: ReviewItem): string {
  return [item.courseCode, item.title].filter(Boolean).join(" — ") || item.code;
}

// ── Selection ──
//
// Skips are held as one flat set of "section:code" strings: codes are only
// unique within their own section, and a flat set keeps toggling a single row
// from re-rendering the whole panel's worth of nested state.

export function skipKey(section: SectionKey, code: string): string {
  return `${section}:${code}`;
}

export function toggleSkip(skipped: Set<string>, key: string): Set<string> {
  const next = new Set(skipped);
  if (!next.delete(key)) next.add(key);
  return next;
}

export function setSectionSkipped(
  skipped: Set<string>,
  section: SectionKey,
  items: ReviewItem[],
  skip: boolean,
): Set<string> {
  const next = new Set(skipped);
  for (const item of items) {
    const key = skipKey(section, item.code);
    if (skip) next.add(key);
    else next.delete(key);
  }
  return next;
}

/** Skips for one section, as a plain count. */
export function countSkipped(
  skipped: Set<string>,
  section: SectionKey,
  items: ReviewItem[],
): number {
  return items.filter((item) => skipped.has(skipKey(section, item.code))).length;
}

/**
 * The flat set, back in the per-section shape the approve endpoint takes.
 *
 * Only sections that actually lost something appear, and an approval with
 * nothing skipped sends no selection at all — the same request as before.
 */
export function buildSkipSelection(
  skipped: Set<string>,
): ChangeSelection | undefined {
  if (skipped.size === 0) return undefined;

  const selection: ChangeSelection = {};
  for (const entry of skipped) {
    const separator = entry.indexOf(":");
    const section = entry.slice(0, separator) as SectionKey;
    const code = entry.slice(separator + 1);
    if (!SECTION_KEYS.includes(section)) continue;
    (selection[section] ??= []).push(code);
  }
  return selection;
}
