"use client";

// Logo · product name · navigation · account, on a white bar closed by the
// brand's lime rule. Below 48rem the navigation folds behind a menu button, so
// the header never pushes the page wider than the phone.

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { cx } from "@/lib/cx";
import { Menu, X } from "@/components/icons";
import { IconButton } from "@/components/ui";
import BrandLogo from "./BrandLogo";
import NavLinks from "./NavLinks";
import UserMenu from "./UserMenu";
import styles from "./AppHeader.module.css";

const NAV_ID = "main-navigation";

export default function AppHeader() {
  const pathname = usePathname();
  const [isNavOpen, setIsNavOpen] = useState(false);

  // Following a link closes the folded menu.
  useEffect(() => {
    setIsNavOpen(false);
  }, [pathname]);

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <BrandLogo href="/generate" />
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.product}>Social Media Marketing</span>
        </div>

        <NavLinks id={NAV_ID} className={cx(styles.nav, isNavOpen && styles.navOpen)} />

        <div className={styles.end}>
          <IconButton
            label={isNavOpen ? "Close menu" : "Open menu"}
            className={styles.menuToggle}
            aria-expanded={isNavOpen}
            aria-controls={NAV_ID}
            onClick={() => setIsNavOpen((open) => !open)}
          >
            {isNavOpen ? <X size={22} /> : <Menu size={22} />}
          </IconButton>
          <UserMenu />
          {/* Slot for the official "Skills for a Stronger Community" tagline.
              Shown once the college supplies the artwork — it is never
              imitated with a script font. */}
        </div>
      </div>
    </header>
  );
}
