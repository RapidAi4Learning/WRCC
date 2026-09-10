import Image from "next/image";
import Link from "next/link";

import { cx } from "@/lib/cx";
import styles from "./BrandLogo.module.css";

// The college's official logo, from wrcc.nsw.edu.au. Replace the file with the
// SVG master when the college supplies it; the dimensions below are the PNG's.
const LOGO_SRC = "/brand/wrcc-logo.png";
const LOGO_WIDTH = 296;
const LOGO_HEIGHT = 70;

interface BrandLogoProps {
  /** Where the logo links to; omit for a plain image (the login page). */
  href?: string;
  size?: "md" | "lg";
  className?: string;
}

export default function BrandLogo({ href, size = "md", className }: BrandLogoProps) {
  const image = (
    <Image
      src={LOGO_SRC}
      alt="Western Riverina Community College"
      width={LOGO_WIDTH}
      height={LOGO_HEIGHT}
      priority
      className={cx(styles.logo, styles[size], className)}
    />
  );
  return href ? (
    <Link href={href} className={styles.link}>
      {image}
    </Link>
  ) : (
    image
  );
}
