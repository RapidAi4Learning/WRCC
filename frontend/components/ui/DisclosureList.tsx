import type { ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./DisclosureList.module.css";

export function DisclosureList({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <ul className={cx(styles.list, className)}>{children}</ul>;
}

export interface DisclosureRowProps {
  /** The always-visible row content; it is the toggle button's label. */
  summary: ReactNode;
  isExpanded: boolean;
  onToggle: () => void;
  /** `inset`: the expanded body sits on a tinted, ruled panel. `flush`: it does not. */
  bodyVariant?: "inset" | "flush";
  children?: ReactNode;
}

/** One row of a list that opens in place to show more. */
export function DisclosureRow({
  summary,
  isExpanded,
  onToggle,
  bodyVariant = "inset",
  children,
}: DisclosureRowProps) {
  return (
    <li className={styles.row}>
      <button
        type="button"
        className={styles.summary}
        onClick={onToggle}
        aria-expanded={isExpanded}
      >
        {summary}
      </button>
      {isExpanded ? (
        <div className={cx(styles.body, styles[bodyVariant])}>{children}</div>
      ) : null}
    </li>
  );
}
