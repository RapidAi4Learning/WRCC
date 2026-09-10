import { cx } from "@/lib/cx";
import { OrderBadge } from "./Badge";
import styles from "./SelectableThumb.module.css";

export interface SelectableThumbProps {
  src: string;
  /** Accessible name. The image itself is decorative: the name says what it is. */
  label: string;
  isSelected: boolean;
  /** 1-based position in the selection; shown only while selected. */
  order?: number;
  onToggle: () => void;
  disabled?: boolean;
  /** `tile`: full-width image in a gallery card. `compact`: a small square. */
  variant?: "tile" | "compact";
  width?: number;
  height?: number;
  className?: string;
}

/** An image that is ticked by clicking it, badged with its place in the order. */
export default function SelectableThumb({
  src,
  label,
  isSelected,
  order,
  onToggle,
  disabled = false,
  variant = "compact",
  width = 96,
  height = 96,
  className,
}: SelectableThumbProps) {
  return (
    <button
      type="button"
      className={cx(styles.thumb, styles[variant], className)}
      onClick={onToggle}
      aria-pressed={isSelected}
      // Explicit, so the order badge never becomes part of the name —
      // `aria-pressed` already carries the selection.
      aria-label={label}
      title={label}
      disabled={disabled}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        width={width}
        height={height}
        loading="lazy"
        className={styles.image}
      />
      {isSelected && order !== undefined ? (
        <OrderBadge n={order} size={variant === "tile" ? "md" : "sm"} isFloating />
      ) : null}
    </button>
  );
}
