"use client";

// The one dialog shell. Portal, backdrop, scroll lock, Escape, click-outside and
// focus containment live here, so no dialog re-implements them — and a dialog
// opened on top of another only ever closes itself.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { useEscapeKey } from "@/hooks/useEscapeKey";
import { cx } from "@/lib/cx";
import type { Platform } from "@/types/content";
import IconButton from "./IconButton";
import styles from "./Modal.module.css";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

// Open modals, in the order they registered. A dialog nested inside another
// mounts in the same commit and React runs the child's effects first, so the
// registration order alone would put the parent on top — nesting depth is
// what decides, and registration order only breaks ties between siblings.
interface OpenModal {
  id: string;
  depth: number;
}
let openStack: OpenModal[] = [];

function topmostId(): string | null {
  let top: OpenModal | null = null;
  for (const modal of openStack) {
    if (top === null || modal.depth >= top.depth) top = modal;
  }
  return top?.id ?? null;
}

const ModalDepth = createContext(0);

export interface ModalProps {
  /** Also the dialog's accessible name. */
  title: ReactNode;
  hint?: ReactNode;
  onClose: () => void;
  size?: "sm" | "md" | "lg";
  /** A top rule in the network's colour, for dialogs about one platform. */
  accent?: Platform;
  children: ReactNode;
}

export default function Modal({
  title,
  hint,
  onClose,
  size = "md",
  accent,
  children,
}: ModalProps) {
  const id = useId();
  const depth = useContext(ModalDepth) + 1;
  const titleId = `${id}-title`;
  const dialogRef = useRef<HTMLDivElement>(null);

  useBodyScrollLock();

  useEffect(() => {
    openStack = [...openStack, { id, depth }];
    return () => {
      openStack = openStack.filter((entry) => entry.id !== id);
    };
  }, [id, depth]);

  const closeIfTopmost = useCallback(() => {
    if (topmostId() === id) onClose();
  }, [id, onClose]);
  useEscapeKey(closeIfTopmost);

  // Focus moves into the dialog, and back to whatever opened it on close.
  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    return () => opener?.focus();
  }, []);

  function containFocus(event: KeyboardEvent<HTMLDivElement>) {
    const dialog = dialogRef.current;
    if (event.key !== "Tab" || event.defaultPrevented || !dialog) return;
    // A dialog stacked on this one handles its own Tab.
    if (!dialog.contains(document.activeElement)) return;
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx(styles.dialog, styles[size])}
        data-accent={accent}
        onKeyDown={containFocus}
      >
        <header className={styles.header}>
          <div>
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            {hint ? <p className={styles.hint}>{hint}</p> : null}
          </div>
          <IconButton label="Close" onClick={onClose}>
            ✕
          </IconButton>
        </header>
        <ModalDepth.Provider value={depth}>{children}</ModalDepth.Provider>
      </div>
    </div>,
    document.body,
  );
}

/** The commit bar at the bottom of a dialog. */
export function ModalFooter({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <footer className={cx(styles.footer, className)}>{children}</footer>;
}
