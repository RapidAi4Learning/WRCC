export interface Course {
  id: string;
  course_code: string;
  title: string;
  category: string | null;
  description: string | null;
  is_accredited: boolean;
  source_url: string | null;
  is_active: boolean;
}

export interface CourseOffering {
  id: string;
  offering_code: string;
  price: number | null;
  status: string;
  places_available: number | null;
  places_text: string | null;
  location: string | null;
  start_date: string | null;
  finish_date: string | null;
  time_text: string | null;
  enrollment_url: string | null;
}

export interface CourseDetail extends Course {
  offerings: CourseOffering[];
}

export type SyncRunStatus =
  | "running"
  | "pending"
  | "approved"
  | "rejected"
  | "failed";

// ── Staged changeset (backend: app/scraper/diff.py) ──

export interface FieldChange {
  from: unknown;
  to: unknown;
}

/** An offering as staged: the scraped fields, keyed by offering code. */
export interface StagedOffering {
  offering_code: string;
  course_code?: string;
  price?: number | null;
  gst?: number | null;
  status?: string | null;
  places_available?: number | null;
  places_text?: string | null;
  location?: string | null;
  start_date?: string | null;
  finish_date?: string | null;
  time_text?: string | null;
  session_count?: number | null;
  session_hours?: number | null;
  enrollment_url?: string | null;
  detail_url?: string | null;
}

export interface StagedCourseAdded {
  course_code: string;
  title: string;
  category: string | null;
  description: string | null;
  is_accredited: boolean;
  source_url: string | null;
  offerings: StagedOffering[];
}

export interface StagedCourseUpdate {
  course_code: string;
  changes: Record<string, FieldChange>;
}

export interface StagedOfferingUpdate {
  offering_code: string;
  course_code: string;
  changes: Record<string, FieldChange>;
}

export interface StagedCourseRemoval {
  course_code: string;
  title: string | null;
  category: string | null;
  offerings_affected: number;
}

export interface StagedOfferingRemoval {
  offering_code: string;
  course_code: string | null;
  start_date: string | null;
  location: string | null;
  price: number | null;
}

// Removals were staged as bare code strings before they carried context; a run
// from before that change can still be sitting in review.
export type RemovalEntry<T> = T | string;

export type ChangesetSection =
  | "courses_added"
  | "courses_updated"
  | "courses_removed"
  | "offerings_added"
  | "offerings_updated"
  | "offerings_removed";

/**
 * Entry codes the reviewer unticked, per section. Only codes travel: the rows
 * that get applied are always the ones the server staged.
 */
export type ChangeSelection = Partial<Record<ChangesetSection, string[]>>;

export interface ChangesetSummary {
  courses_added: number;
  courses_updated: number;
  courses_removed: number;
  offerings_added: number;
  offerings_updated: number;
  offerings_removed: number;
}

export interface Changeset {
  courses_added?: StagedCourseAdded[];
  courses_updated?: StagedCourseUpdate[];
  courses_removed?: RemovalEntry<StagedCourseRemoval>[];
  offerings_added?: StagedOffering[];
  offerings_updated?: StagedOfferingUpdate[];
  offerings_removed?: RemovalEntry<StagedOfferingRemoval>[];
  summary?: ChangesetSummary;
}

export interface SyncRun {
  id: string;
  status: SyncRunStatus;
  courses_found: number;
  offerings_found: number;
  changeset: Changeset | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  reviewed_at: string | null;
  created_at: string;
}
