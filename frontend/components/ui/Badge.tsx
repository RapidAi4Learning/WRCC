import type { HTMLAttributes } from "react";

import { cx } from "@/lib/cx";
import styles from "./Badge.module.css";

export type BadgeTone =
  | "neutral"
  | "outline"
  | "accent"
  | "solid"
  | "warn"
  | "danger"
  | "facebook"
  | "instagram"
  | "linkedin";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  /** `pill`: rounded label. `tag`: small squared uppercase marker. */
  shape?: "pill" | "tag";
  /** Uppercase, tracked — for the one badge that heads a panel. */
  isCaps?: boolean;
  isStruck?: boolean;
}

export default function Badge({
  tone = "neutral",
  shape = "pill",
  isCaps = false,
  isStruck = false,
  className,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cx(
        styles.badge,
        styles[shape],
        styles[tone],
        isCaps && styles.caps,
        isStruck && styles.struck,
        className,
      )}
      {...rest}
    />
  );
}

export interface OrderBadgeProps {
  /** 1-based position. */
  n: number;
  size?: "sm" | "md";
  /** Pinned to the top-left corner of a positioned parent (an image). */
  isFloating?: boolean;
  className?: string;
}

/** A position in an ordered selection — the carousel order, not a count. */
export function OrderBadge({ n, size = "md", isFloating = false, className }: OrderBadgeProps) {
  return (
    <span
      className={cx(styles.order, styles[`order-${size}`], isFloating && styles.floating, className)}
      aria-hidden="true"
    >
      {n}
    </span>
  );
}
