// Ordered, capped selections — the images a post sends, in carousel order.
// Pure, so the Media panel and the publish dialog cannot disagree about what a
// tick does.

export interface ToggleResult {
  list: string[];
  /** True when the id was refused because the list was already full. */
  isOverLimit: boolean;
}

/** Remove `id` if present, else append it — unless that would pass `max`. */
export function toggleOrdered(
  list: readonly string[],
  id: string,
  max: number,
): ToggleResult {
  if (list.includes(id)) {
    return { list: list.filter((entry) => entry !== id), isOverLimit: false };
  }
  if (list.length >= max) return { list: [...list], isOverLimit: true };
  return { list: [...list, id], isOverLimit: false };
}

/** Swap the entry at `index` with its neighbour `delta` places away. */
export function moveItem(
  list: readonly string[],
  index: number,
  delta: number,
): string[] {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) {
    return [...list];
  }
  return list.map((entry, position) => {
    if (position === index) return list[target];
    if (position === target) return list[index];
    return entry;
  });
}
