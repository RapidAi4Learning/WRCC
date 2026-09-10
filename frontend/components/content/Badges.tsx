import { PLATFORM_LABELS, STATUS_LABELS } from "@/lib/platforms";
import { cx } from "@/lib/cx";
import type { ContentStatus, Platform } from "@/types/content";
import { PlatformIcon } from "@/components/icons";
import { Badge, type BadgeTone } from "@/components/ui";
import styles from "./Badges.module.css";

const STATUS_TONES: Record<ContentStatus, BadgeTone> = {
  draft: "neutral",
  pending_approval: "warn",
  approved: "success",
  rejected: "danger",
  // Deliberately louder than approved: "ready to go" and "already gone" being
  // confusable is what causes a post to be published twice.
  published: "solid",
  archived: "neutral",
};

/** Compact platform label for dense rows: a tinted pill. */
export function PlatformBadge({ platform }: { platform: Platform }) {
  return (
    <Badge tone={platform}>
      <PlatformIcon platform={platform} size={12} tone="mono" />
      {PLATFORM_LABELS[platform]}
    </Badge>
  );
}

/**
 * The network's full-colour mark with its name beside it — for places where
 * the platform is the thing being chosen (compose chips, result tabs, cards).
 */
export function PlatformName({
  platform,
  size = "md",
  className,
}: {
  platform: Platform;
  size?: "md" | "lg";
  className?: string;
}) {
  return (
    <span className={cx(styles.name, styles[size], className)} data-platform={platform}>
      <PlatformIcon platform={platform} size={size === "lg" ? 28 : 22} />
      {PLATFORM_LABELS[platform]}
    </span>
  );
}

export function StatusBadge({ status }: { status: ContentStatus }) {
  return (
    <Badge tone={STATUS_TONES[status]} isStruck={status === "archived"}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}
