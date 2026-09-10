"use client";

import { useEffect } from "react";

/** Call `onEscape` whenever Escape is pressed anywhere, while `isActive`. */
export function useEscapeKey(onEscape: () => void, isActive = true): void {
  useEffect(() => {
    if (!isActive) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onEscape();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onEscape, isActive]);
}
