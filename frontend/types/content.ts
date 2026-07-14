export type Platform = "facebook" | "instagram" | "linkedin";

export type ContentStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "archived";

export interface ContentItem {
  id: string;
  platform: Platform;
  topic: string | null;
  reference_url: string | null;
  notes: string | null;
  course_id: string | null;
  generation_group: string | null;
  variant_style: string;
  generated_body: string;
  edited_body: string | null;
  body: string;
  hashtags: string[];
  call_to_action: string | null;
  status: ContentStatus;
  ai_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
}

export interface GenerateContentInput {
  topic?: string;
  reference_url?: string;
  notes?: string;
  course_id?: string;
  platforms: Platform[];
}

export interface GenerateContentResult {
  generation_group: string;
  items: ContentItem[];
  warnings: string[];
}

export interface ContentImage {
  id: string;
  content_item_id: string;
  prompt: string;
  model: string;
  created_at: string;
  file_url: string;
}

export interface ImageSuggestions {
  prompts: string[];
}

export type WorkflowAction =
  | "submit"
  | "approve"
  | "reject"
  | "archive"
  | "restore"
  | "duplicate"
  | "regenerate";
