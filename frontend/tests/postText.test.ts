import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { composePostText } from "@/lib/postText";
import type { ContentItem } from "@/types/content";

interface SharedCase {
  name: string;
  body: string;
  call_to_action: string | null;
  hashtags: string[];
  expected: string;
}

// The cross-language contract, also iterated by the backend suite. Asserting
// hardcoded strings on each side independently would let one implementation
// change while both suites stayed green — and the first sign would be a Copy
// button producing text that differs from what was published.
// Resolved from the vitest working directory (the frontend root) rather than
// import.meta.url, which vitest does not serve as a file: URL.
const sharedCases: SharedCase[] = JSON.parse(
  readFileSync(resolve(process.cwd(), "../shared/post-text-cases.json"), "utf8"),
).cases;

function item(overrides: Partial<ContentItem> = {}): ContentItem {
  return {
    id: "item-1",
    platform: "facebook",
    topic: "Spring enrolments",
    reference_url: null,
    notes: null,
    course_id: null,
    generation_group: "group-1",
    variant_style: "direct",
    generated_body: "Enrol now: our courses.",
    edited_body: null,
    body: "Enrol now: our courses.",
    hashtags: ["#WRCC", "#LearnLocal"],
    call_to_action: "Book your spot.",
    status: "draft",
    ai_metadata: null,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
    reviewed_at: null,
    ...overrides,
  };
}

describe("composePostText — the shared contract with the backend", () => {
  it.each(sharedCases)("$name", ({ body, call_to_action, hashtags, expected }) => {
    expect(
      composePostText(item({ body, call_to_action, hashtags })),
    ).toBe(expected);
  });
});

describe("composePostText", () => {
  it("orders body, call to action and hashtags for pasting into a network", () => {
    expect(composePostText(item())).toBe(
      "Enrol now: our courses.\n\nBook your spot.\n\n#WRCC #LearnLocal",
    );
  });

  it("omits the call to action when the item has none", () => {
    expect(composePostText(item({ call_to_action: null }))).toBe(
      "Enrol now: our courses.\n\n#WRCC #LearnLocal",
    );
  });

  it("omits the hashtag line when there are no hashtags", () => {
    expect(composePostText(item({ hashtags: [] }))).toBe(
      "Enrol now: our courses.\n\nBook your spot.",
    );
  });

  it("drops blank hashtag entries instead of emitting stray spaces", () => {
    expect(composePostText(item({ hashtags: ["#WRCC", "  ", ""] }))).toBe(
      "Enrol now: our courses.\n\nBook your spot.\n\n#WRCC",
    );
  });

  it("copies the edited body, not the original generation", () => {
    const edited = item({
      edited_body: "Enrol before Friday.",
      body: "Enrol before Friday.",
    });
    expect(composePostText(edited)).toContain("Enrol before Friday.");
    expect(composePostText(edited)).not.toContain("our courses");
  });

  it("trims surrounding whitespace so the paste has no leading blank lines", () => {
    const padded = item({ body: "  Enrol now.  ", call_to_action: "  Go.  " });
    expect(composePostText(padded)).toBe("Enrol now.\n\nGo.\n\n#WRCC #LearnLocal");
  });

  it("returns an empty string when the item has nothing to copy", () => {
    expect(
      composePostText(item({ body: "", call_to_action: null, hashtags: [] })),
    ).toBe("");
  });
});
