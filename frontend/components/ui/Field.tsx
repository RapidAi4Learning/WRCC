import type { ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./Field.module.css";

export interface FieldProps {
  label: ReactNode;
  /** Id of the control the label names. Omit only when the control labels itself. */
  htmlFor?: string;
  isOptional?: boolean;
  hint?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** Label + control + optional hint, stacked. */
export default function Field({
  label,
  htmlFor,
  isOptional = false,
  hint,
  className,
  children,
}: FieldProps) {
  return (
    <div className={cx(styles.field, className)}>
      <label className={styles.label} htmlFor={htmlFor}>
        {label}
        {isOptional ? <span className={styles.optional}> (optional)</span> : null}
      </label>
      {children}
      {hint ? <p className={styles.hint}>{hint}</p> : null}
    </div>
  );
}
