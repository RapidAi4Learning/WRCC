"use client";

import { useId, type ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./SegmentedControl.module.css";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** Short secondary line, e.g. an expected duration. */
  hint?: string;
}

export interface SegmentedControlProps<T extends string> {
  /** Visible label; also the group's accessible name. */
  label: string;
  /** Radio group name — unique per page. */
  name: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  description?: ReactNode;
  className?: string;
}

/**
 * One choice out of a few, drawn as a track of equal segments. Native radios
 * underneath, so arrow keys, focus and form semantics come for free.
 */
export default function SegmentedControl<T extends string>({
  label,
  name,
  value,
  options,
  onChange,
  description,
  className,
}: SegmentedControlProps<T>) {
  const id = useId();
  const labelId = `${id}-label`;
  const descriptionId = `${id}-description`;

  return (
    <div className={cx(styles.field, className)}>
      <span id={labelId} className={styles.label}>
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        aria-describedby={description ? descriptionId : undefined}
        className={styles.track}
      >
        {options.map((option) => (
          <label key={option.value} className={styles.option}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={option.value === value}
              onChange={() => onChange(option.value)}
              className={styles.input}
            />
            <span className={styles.optionLabel}>{option.label}</span>
            {option.hint ? <span className={styles.hint}>{option.hint}</span> : null}
          </label>
        ))}
      </div>
      {description ? (
        <p id={descriptionId} className={styles.description}>
          {description}
        </p>
      ) : null}
    </div>
  );
}
