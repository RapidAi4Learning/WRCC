import type { ReactNode } from "react";

import NavLinks from "@/components/NavLinks";
import UserMenu from "@/components/UserMenu";
import styles from "./shell.module.css";

// Authenticated app shell: middleware guarantees a session cookie exists for
// every route in this group, so the header can always render the user menu.
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>WRCC</span>
          <span className={styles.brandName}>Content Studio</span>
        </div>
        <NavLinks />
        <UserMenu />
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
