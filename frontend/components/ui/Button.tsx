import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./Button.module.css";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "danger"
  | "link"
  | "linkDanger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonStyle {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Stretch to the container's width. */
  block?: boolean;
}

/** The button look, for elements that are not <button> (links, <a download>). */
export function buttonClass({
  variant = "secondary",
  size = "md",
  block = false,
  className,
}: ButtonStyle & { className?: string } = {}): string {
  return cx(styles.button, styles[size], styles[variant], block && styles.block, className);
}

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    ButtonStyle {
  /** Decorative leading icon; hidden from assistive tech. */
  icon?: ReactNode;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, block, icon, className, type = "button", children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // Explicit, because a bare <button> inside a form is a submit button.
      type={type}
      className={buttonClass({ variant, size, block, className })}
      {...rest}
    >
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
});

export default Button;
