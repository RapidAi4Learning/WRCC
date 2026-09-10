import { cx } from "@/lib/cx";
import styles from "./Card.module.css";

export interface CardStyle {
  /** `raised`: white with a soft shadow. `outline`: border only, transparent. */
  variant?: "raised" | "outline";
  padding?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

/**
 * The surface look, as a class, so any element (form, article, section) can be
 * a card without a wrapper div.
 */
export function cardClass({ variant = "raised", padding = "md", className }: CardStyle = {}): string {
  return cx(styles.card, styles[variant], styles[`pad-${padding}`], className);
}
