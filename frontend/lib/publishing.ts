// Platforms whose live publishing is held shut on our side, independent of
// anything the backend preflight says.
//
// The backend rules answer "is this post ready?"; this answers the separate
// question "are we allowed to post to this network at all yet?". A network can
// be perfectly configured in code and still be unusable because the app itself
// has not cleared the network's own review — which is not a property of any
// single post, so preflight is the wrong place for it.
//
// To lift a hold, delete its entry. Nothing else needs changing.

import type { Platform } from "@/types/content";

export const PUBLISHING_HOLDS: Partial<Record<Platform, string>> = {
  // The LinkedIn app has no verified company page yet, so the organisation
  // scopes it posts with (w_organization_social and friends) are not granted
  // and no redirect URI is registered — an attempt would fail at the OAuth
  // step. Remove this once the app is verified and the products are approved.
  linkedin:
    "LinkedIn publishing is on hold until our LinkedIn app is verified and approved for posting.",
};

export function publishingHold(platform: Platform): string | null {
  return PUBLISHING_HOLDS[platform] ?? null;
}
