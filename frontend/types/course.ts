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

export interface ChangesetSummary {
  courses_added: number;
  courses_updated: number;
  courses_removed: number;
  offerings_added: number;
  offerings_updated: number;
  offerings_removed: number;
}

export interface SyncRun {
  id: string;
  status: SyncRunStatus;
  courses_found: number;
  offerings_found: number;
  changeset: ({ summary?: ChangesetSummary } & Record<string, unknown>) | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  reviewed_at: string | null;
  created_at: string;
}
