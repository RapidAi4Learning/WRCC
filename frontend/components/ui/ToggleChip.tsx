import type { InputHTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./ToggleChip.module.css";

export interface ToggleChipProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className"> {
  className?: string;
  /** The chip's content, which is also the checkbox's label. */
  children: ReactNode;
}

/** A checkbox drawn as a chip: the chip itself shows the checked state. */
export default function ToggleChip({ className, children, ...rest }: ToggleChipProps) {
  return (
    <label className={cx(styles.chip, className)}>
      <input type="checkbox" className={styles.input} {...rest} />
      {children}
    </label>
  );
}
