"use client";

// Current-user chip + logout, shown in the app shell header.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getCurrentUser, logout } from "@/lib/auth";
import type { AuthUser } from "@/types/auth";
import { Button } from "@/components/ui";
import styles from "./UserMenu.module.css";

export default function UserMenu() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);

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

  async function handleLogout() {
    try {
      await logout();
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <div className={styles.menu}>
      {user ? <span className={styles.email}>{user.email}</span> : null}
      <Button size="sm" onClick={handleLogout}>
        Log out
      </Button>
    </div>
  );
}
