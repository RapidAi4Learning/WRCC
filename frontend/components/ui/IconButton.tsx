import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cx } from "@/lib/cx";
import styles from "./IconButton.module.css";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** The accessible name — an icon alone has none. */
  label: string;
  variant?: "plain" | "outline";
  size?: "sm" | "md";
}

const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = "plain", size = "md", className, type = "button", children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      className={cx(styles.button, styles[variant], styles[size], className)}
      {...rest}
    >
      <span aria-hidden="true" className={styles.glyph}>
        {children}
      </span>
    </button>
  );
});

export default IconButton;
