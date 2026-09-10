import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./EmptyState.module.css";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  /** Decorative illustration above the title. */
  icon?: ReactNode;
  /** `dashed`: a drop-zone style frame. `plain`: centred text only. */
  variant?: "dashed" | "plain";
  size?: "sm" | "md" | "lg";
  children?: ReactNode;
}

/** What a region says when it has nothing to show yet (or is still loading). */
export default function EmptyState({
  title,
  icon,
  variant = "plain",
  size = "md",
  className,
  children,
  ...rest
}: EmptyStateProps) {
  return (
    <div className={cx(styles.empty, styles[variant], styles[size], className)} {...rest}>
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {title ? <p className={styles.title}>{title}</p> : null}
      {children ? <p className={styles.message}>{children}</p> : null}
    </div>
  );
}
