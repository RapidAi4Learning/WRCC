"use client";

import { useEffect } from "react";

/**
 * Stop the page behind an overlay from scrolling while `isActive`. Restores the
 * previous value rather than clearing it, so stacked overlays unwind in order.
 */
export function useBodyScrollLock(isActive = true): void {
  useEffect(() => {
    if (!isActive) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [isActive]);
}
