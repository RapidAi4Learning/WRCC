import { cx } from "@/lib/cx";
import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  /** `line`: a text-sized bar. `block`: a suggestion-sized card. `image`: a square. */
  variant?: "line" | "block" | "image";
  className?: string;
}

/** A pulsing placeholder for content still on its way. Decorative. */
export default function Skeleton({ variant = "block", className }: SkeletonProps) {
  return <div className={cx(styles.skeleton, styles[variant], className)} aria-hidden="true" />;
}
