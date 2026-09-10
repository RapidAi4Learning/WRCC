"use client";

// The signed-in user's avatar, opening a small menu with who they are and the
// way out. Replaces the bare email + "Log out" pair that crowded the header.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useEscapeKey } from "@/hooks/useEscapeKey";
import { getCurrentUser, logout } from "@/lib/auth";
import { initials } from "@/lib/initials";
import type { AuthUser } from "@/types/auth";
import { ChevronDown, LogOut } from "@/components/icons";
import styles from "./UserMenu.module.css";

function avatarText(user: AuthUser | null): string {
  if (!user) return "";
  return initials(user.display_name.trim() || user.email.split("@")[0]);
}

export default function UserMenu() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    getCurrentUser({ signal: controller.signal })
      .then(setUser)
      .catch(() => {
        // Session expired mid-navigation: middleware handles the redirect on
        // the next page load; surface nothing here.
      });
    return () => controller.abort();
  }, []);

  const close = useCallback(() => setIsOpen(false), []);
  useEscapeKey(close, isOpen);

  // A menu opened from the keyboard should put focus on its first item; a
  // click anywhere outside closes it.
  useEffect(() => {
    if (!isOpen) return;
    firstItemRef.current?.focus();
    function handlePointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen]);

  async function handleLogout() {
    try {
      await logout();
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <div ref={rootRef} className={styles.menu}>
      <button
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={user ? `Account: ${user.email}` : "Account"}
        onClick={() => setIsOpen((open) => !open)}
      >
        <span className={styles.avatar} aria-hidden="true">
          {avatarText(user)}
        </span>
        <ChevronDown size={18} aria-hidden="true" className={styles.chevron} />
      </button>

      {isOpen ? (
        <div className={styles.panel} role="menu" aria-label="Account">
          {user ? (
            <div className={styles.identity}>
              <p className={styles.name}>{user.display_name}</p>
              <p className={styles.email}>{user.email}</p>
            </div>
          ) : null}
          <button
            ref={firstItemRef}
            type="button"
            role="menuitem"
            className={styles.item}
            onClick={() => void handleLogout()}
          >
            <LogOut size={16} aria-hidden="true" />
            Log out
          </button>
        </div>
      ) : null}
    </div>
  );
}
