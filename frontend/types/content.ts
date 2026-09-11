export type Platform = "facebook" | "instagram" | "linkedin";

export type ContentStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  // Live on the network. Distinct from "approved", which only means ready to
  // go — confusing the two is how a post gets published twice.
  | "published"
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

// Speed against copy quality for one generation. The server accepts exactly
// these; "high" is not offered (see docs/GENERATION-LATENCY-PLAN.md).
export type ReasoningEffort = "minimal" | "low" | "medium";

export interface GenerateContentInput {
  topic?: string;
  reference_url?: string;
  notes?: string;
  course_id?: string;
  platforms: Platform[];
  // Absent keeps the server's OPENAI_REASONING_EFFORT.
  reasoning_effort?: ReasoningEffort;
}

export interface GenerateContentResult {
  generation_group: string;
  items: ContentItem[];
  warnings: string[];
}

// Where an asset's bytes came from. Uploaded ones have a filename and no
// prompt; generated ones the reverse.
export type MediaSource = "generated" | "uploaded";

export interface MediaAsset {
  id: string;
  source: MediaSource;
  prompt: string | null;
  model: string | null;
  filename: string | null;
  mime_type: string;
  width: number;
  height: number;
  byte_size: number;
  alt_text: string | null;
  created_at: string;
  file_url: string;
}

// One entry in a post's ordered selection. Position is the carousel sequence.
export interface ItemMedia {
  media_asset_id: string;
  position: number;
  alt_text: string | null;
}

export interface MediaLibrary {
  // The whole generation group, sibling platforms included.
  library: MediaAsset[];
  // Only what this post sends, in order.
  selection: ItemMedia[];
  max_images: number;
}

export interface SetSelectionResult {
  selection: ItemMedia[];
  // Siblings `apply_to_group` could not update, named rather than trimmed.
  warnings: string[];
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
