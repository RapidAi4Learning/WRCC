"use client";

import type { ButtonHTMLAttributes, KeyboardEvent, ReactNode } from "react";

import { cx } from "@/lib/cx";
import styles from "./Tabs.module.css";

export interface TabListProps {
  label: string;
  /** `pills`: separate rounded tabs. `segmented`: one track, equal-width tabs. */
  variant?: "pills" | "segmented";
  className?: string;
  children: ReactNode;
}

/**
 * A row of tabs. Arrow keys move between them and select as they go (roving
 * tabindex), so the row is a single Tab stop.
 */
export function TabList({ label, variant = "pills", className, children }: TabListProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'),
    );
    const current = tabs.indexOf(document.activeElement as HTMLButtonElement);
    if (current === -1) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(current + step + tabs.length) % tabs.length];
    next.focus();
    next.click();
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className={cx(styles.list, styles[variant], className)}
      onKeyDown={handleKeyDown}
    >
      {children}
    </div>
  );
}

export interface TabProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  isSelected: boolean;
}

export function Tab({ isSelected, className, ...rest }: TabProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isSelected}
      tabIndex={isSelected ? 0 : -1}
      className={cx(styles.tab, className)}
      {...rest}
    />
  );
}
