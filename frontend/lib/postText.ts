import type { ContentItem } from "@/types/content";

// The API keeps body, call to action and hashtags as separate fields, but a
// social network expects one blob of text. Hashtags go last — the convention
// on Facebook/Instagram/LinkedIn — with the CTA sitting between them and the
// body so the ask is not buried under the tags.
export function composePostText(item: ContentItem): string {
  const hashtags = item.hashtags
    .map((hashtag) => hashtag.trim())
    .filter((hashtag) => hashtag.length > 0)
    .join(" ");

  return [item.body.trim(), (item.call_to_action ?? "").trim(), hashtags]
    .filter((section) => section.length > 0)
    .join("\n\n");
}
