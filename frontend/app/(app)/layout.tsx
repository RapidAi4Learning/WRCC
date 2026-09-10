import type { ReactNode } from "react";

import AppHeader from "@/components/layout/AppHeader";
import PageBackground from "@/components/layout/PageBackground";
import styles from "./shell.module.css";

// Authenticated app shell: middleware guarantees a session cookie exists for
// every route in this group, so the header can always render the user menu.
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <PageBackground />
      <AppHeader />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
