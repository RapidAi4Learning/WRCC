import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Figtree, Outfit } from "next/font/google";

import "@/styles/tokens.css";
import "@/styles/globals.css";

// Self-hosted at build time by next/font: no request to Google at runtime and
// no layout shift while the faces load. tokens.css reads the two variables.
const figtree = Figtree({ subsets: ["latin"], display: "swap", variable: "--font-figtree" });
const outfit = Outfit({ subsets: ["latin"], display: "swap", variable: "--font-outfit" });

export const metadata: Metadata = {
  title: "WRCC Social Media Marketing",
  description:
    "Social content generation and course catalog studio for Western Riverina Community College.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${figtree.variable} ${outfit.variable}`}>
      <body>{children}</body>
    </html>
  );
}
