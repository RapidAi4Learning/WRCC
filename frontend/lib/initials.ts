/**
 * Up to two initials for an avatar: "Western Riverina Community College" →
 * "WR", "alex.smith" → "AS". Separators other than spaces count, so an email's
 * local part works as a fallback name.
 */
export function initials(name: string): string {
  return name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}
