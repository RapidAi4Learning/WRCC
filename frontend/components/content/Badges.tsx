import { PLATFORM_LABELS, STATUS_LABELS } from "@/lib/platforms";
import type { ContentStatus, Platform } from "@/types/content";
import { Badge, type BadgeTone } from "@/components/ui";

const STATUS_TONES: Record<ContentStatus, BadgeTone> = {
  draft: "neutral",
  pending_approval: "warn",
  approved: "accent",
  rejected: "danger",
  // Deliberately louder than approved: "ready to go" and "already gone" being
  // confusable is what causes a post to be published twice.
  published: "solid",
  archived: "neutral",
};

export function PlatformBadge({ platform }: { platform: Platform }) {
  return <Badge tone={platform}>{PLATFORM_LABELS[platform]}</Badge>;
}

export function StatusBadge({ status }: { status: ContentStatus }) {
  return (
    <Badge tone={STATUS_TONES[status]} isStruck={status === "archived"}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}
