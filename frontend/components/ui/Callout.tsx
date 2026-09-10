import type { HTMLAttributes } from "react";

import { cx } from "@/lib/cx";
import styles from "./Callout.module.css";

export type CalloutTone = "danger" | "warn" | "success" | "neutral";

export interface CalloutProps extends HTMLAttributes<HTMLElement> {
  tone: CalloutTone;
  size?: "sm" | "md";
  /** A heavy left rule, for the message that must stop the eye. */
  isRuled?: boolean;
  as?: "p" | "div" | "ul";
}

/**
 * An inline message. It deliberately has no default role: whether a message is
 * an `alert`, a `status` or just text is the caller's decision, and each call
 * site keeps the semantics it had.
 */
export default function Callout({
  tone,
  size = "md",
  isRuled = false,
  as: Element = "p",
  className,
  ...rest
}: CalloutProps) {
  return (
    <Element
      className={cx(
        styles.callout,
        styles[tone],
        styles[size],
        isRuled && styles.ruled,
        Element === "ul" && styles.list,
        className,
      )}
      {...rest}
    />
  );
}
