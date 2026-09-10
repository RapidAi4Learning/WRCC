"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cx } from "@/lib/cx";
import styles from "./NavLinks.module.css";

const LINKS = [
  { href: "/generate", label: "Generate" },
  { href: "/history", label: "History" },
  { href: "/catalog", label: "Catalog" },
  { href: "/settings", label: "Settings" },
];

interface NavLinksProps {
  id?: string;
  className?: string;
}

export default function NavLinks({ id, className }: NavLinksProps) {
  const pathname = usePathname();
  return (
    <nav id={id} aria-label="Main navigation" className={cx(styles.nav, className)}>
      {LINKS.map(({ href, label }) => (
        <Link
          key={href}
          href={href}
          className={styles.link}
          aria-current={pathname.startsWith(href) ? "page" : undefined}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
