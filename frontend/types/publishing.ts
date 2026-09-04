import type { Platform } from "@/types/content";

// One Meta authorisation covers Facebook and Instagram, so the OAuth provider
// is not the same thing as the platform a card is shown for.
export type SocialProvider = "meta" | "linkedin";

export interface SocialAccount {
  id: string;
  platform: Platform;
  external_id: string;
  display_name: string;
  handle: string | null;
  scopes: string[];
  is_active: boolean;
  token_expires_at: string | null;
  // Derived server-side, including the early-expiry skew, so the UI never has
  // to reimplement that rule.
  token_expired: boolean;
  connected_at: string;
}

export interface AuthorizeUrl {
  provider: SocialProvider;
  authorize_url: string;
}

export interface AccountVerification {
  account: SocialAccount;
  // A dead token is information, not a request error — the check ran either way.
  ok: boolean;
  error: string | null;
  error_code: string | null;
}

export type PublishStatus = "pending" | "succeeded" | "failed";

export interface Publication {
  id: string;
  content_item_id: string;
  social_account_id: string | null;
  // Exactly what went out, in order.
  media_asset_ids: string[];
  status: PublishStatus;
  external_post_id: string | null;
  permalink: string | null;
  error: string | null;
  error_code: string | null;
  request_summary: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

export interface PublishPreflight {
  ready: boolean;
  blockers: string[];
  warnings: string[];
  platform: Platform;
  text: string;
  char_count: number;
  char_limit: number;
  hashtag_count: number;
  // The selection this preflight evaluated, in publish order.
  image_ids: string[];
  image_required: boolean;
  max_images: number;
  account: SocialAccount | null;
}
