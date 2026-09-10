import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cx } from "@/lib/cx";
import styles from "./TextInput.module.css";

type ControlSize = "sm" | "md";

interface ControlChrome {
  /** Decorative leading icon; hidden from assistive tech. */
  icon?: ReactNode;
  controlSize?: ControlSize;
  /** Class for the wrapper, which is the element that sits in the layout. */
  className?: string;
}

export interface TextInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "className">,
    ControlChrome {
  /** Something inside the right edge of the field, e.g. a show-password toggle. */
  trailing?: ReactNode;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { icon, trailing, controlSize = "md", className, ...rest },
  ref,
) {
  return (
    <div
      className={cx(
        styles.control,
        styles[controlSize],
        icon ? styles.hasIcon : null,
        trailing ? styles.hasTrailing : null,
        className,
      )}
    >
      {icon ? (
        <span className={styles.leading} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <input ref={ref} className={styles.input} {...rest} />
      {trailing ? <span className={styles.trailing}>{trailing}</span> : null}
    </div>
  );
});

export interface TextAreaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className">,
    ControlChrome {}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { icon, controlSize = "md", className, ...rest },
  ref,
) {
  return (
    <div
      className={cx(
        styles.control,
        styles.multiline,
        styles[controlSize],
        icon ? styles.hasIcon : null,
        className,
      )}
    >
      {icon ? (
        <span className={styles.leading} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <textarea ref={ref} className={styles.input} {...rest} />
    </div>
  );
});

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  controlSize?: ControlSize;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { controlSize = "sm", className, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cx(styles.input, styles.select, styles[controlSize], className)}
      {...rest}
    />
  );
});
