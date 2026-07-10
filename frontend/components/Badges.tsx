import type { ContentStatus, Platform } from "@/types/content";
import styles from "./Badges.module.css";

const PLATFORM_LABELS: Record<Platform, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
};

const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  archived: "Archived",
};

export function PlatformBadge({ platform }: { platform: Platform }) {
  return (
    <span className={`${styles.platform} ${styles[platform]}`}>
      {PLATFORM_LABELS[platform]}
    </span>
  );
}

export function StatusBadge({ status }: { status: ContentStatus }) {
  return (
    <span className={`${styles.status} ${styles[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
