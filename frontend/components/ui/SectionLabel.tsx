import type { LabelHTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./SectionLabel.module.css";

export interface SectionLabelProps extends LabelHTMLAttributes<HTMLElement> {
  as?: "span" | "h2" | "h3" | "legend" | "label";
  /** A numbered step ("1 · Create a post"). */
  step?: number;
  size?: "xs" | "sm";
  tone?: "muted" | "brand";
  children: ReactNode;
}

/** The small uppercase heading over a group of fields or a panel section. */
export default function SectionLabel({
  as: Element = "span",
  step,
  size = "xs",
  tone = "muted",
  className,
  children,
  ...rest
}: SectionLabelProps) {
  return (
    <Element className={cx(styles.label, styles[size], styles[tone], className)} {...rest}>
      {step !== undefined ? (
        <span className={styles.step}>
          <span className={styles.stepNumber}>{step}</span> ·{" "}
        </span>
      ) : null}
      {children}
    </Element>
  );
}
