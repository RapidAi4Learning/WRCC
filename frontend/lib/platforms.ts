// Single source for how platforms and workflow statuses are named and ordered.
// Badges, filters, the compose form and prose ("Publish to LinkedIn") all read
// from here, so a network is never spelled two ways.

import type { ContentStatus, Platform } from "@/types/content";

export const PLATFORMS: readonly Platform[] = ["facebook", "instagram", "linkedin"];

export const PLATFORM_LABELS: Record<Platform, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
};

export const STATUSES: readonly ContentStatus[] = [
  "draft",
  "pending_approval",
  "approved",
  "rejected",
  "published",
  "archived",
];

export const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  published: "Published",
  archived: "Archived",
};
