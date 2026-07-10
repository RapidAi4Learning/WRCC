"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import styles from "./NavLinks.module.css";

const LINKS = [
  { href: "/generate", label: "Generate" },
  { href: "/history", label: "History" },
  { href: "/catalog", label: "Catalog" },
];

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation" className={styles.nav}>
      {LINKS.map(({ href, label }) => (
        <Link
          key={href}
          href={href}
          className={pathname.startsWith(href) ? styles.active : styles.link}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
