"use client";

import { useCallback, useEffect, useState } from "react";

/** One of a fixed set of choices, remembered per browser.
 *
 *  Read after mount rather than in the initial state: pages are prerendered on
 *  the server, where there is no storage, and a first browser render that
 *  differed from it would not hydrate. A stored value that is no longer offered
 *  is ignored, and blocked storage (private mode, site data off) just means the
 *  choice is not remembered. `offered` must be a stable (module-level) array.
 */
export function useStoredChoice<T extends string>(
  storageKey: string,
  offered: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(fallback);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      const match = offered.find((choice) => choice === stored);
      if (match !== undefined) setValue(match);
    } catch {
      // Storage blocked: keep the fallback.
    }
  }, [storageKey, offered]);

  const choose = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(storageKey, next);
      } catch {
        // Not remembered this time; the choice still applies to this page.
      }
    },
    [storageKey],
  );

  return [value, choose];
}
