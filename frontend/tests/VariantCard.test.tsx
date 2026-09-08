import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VariantCard from "@/components/VariantCard";
import type { ContentItem } from "@/types/content";
import type { Publication } from "@/types/publishing";

const { mockFetchPublications, mockFetchContentItem, mockPreflight, mockPublish } =
  vi.hoisted(() => ({
    mockFetchPublications: vi.fn(),
    mockFetchContentItem: vi.fn(),
    mockPreflight: vi.fn(),
    mockPublish: vi.fn(),
  }));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  },
  contentAction: vi.fn(),
  editContent: vi.fn(),
  fetchContentItem: mockFetchContentItem,
  fetchPublications: mockFetchPublications,
  fetchPublishPreflight: mockPreflight,
  publishContent: mockPublish,
  fetchMedia: vi
    .fn()
    .mockResolvedValue({ library: [], selection: [], max_images: 10 }),
  fetchImageSuggestions: vi.fn().mockResolvedValue({ prompts: [] }),
  generateImage: vi.fn(),
  uploadMedia: vi.fn(),
  saveMediaSelection: vi.fn(),
  deleteMediaAsset: vi.fn(),
  imageFileUrl: () => "http://api.test/image.png",
}));

beforeEach(() => {
  mockFetchPublications.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

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

describe("VariantCard", () => {
  it("renders body, hashtags, CTA and the variant label", () => {
    render(<VariantCard item={item()} onChange={vi.fn()} />);
    expect(screen.getByText("Enrol now: our courses.")).toBeInTheDocument();
    expect(screen.getByText("#WRCC #LearnLocal")).toBeInTheDocument();
    expect(screen.getByText("Book your spot.")).toBeInTheDocument();
    expect(screen.getByText("A · Direct")).toBeInTheDocument();
  });

  it("offers submit (not approve) while the item is a draft", () => {
    render(<VariantCard item={item()} onChange={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "Submit for approval" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("offers approve/reject once pending approval", () => {
    render(
      <VariantCard item={item({ status: "pending_approval" })} onChange={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Submit for approval" }),
    ).not.toBeInTheDocument();
  });

  it("only offers restore (and duplicate) when archived", () => {
    render(<VariantCard item={item({ status: "archived" })} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("shows the platform badge only when asked", () => {
    const { rerender } = render(<VariantCard item={item()} onChange={vi.fn()} />);
    expect(screen.queryByText("Facebook")).not.toBeInTheDocument();
    rerender(<VariantCard item={item()} onChange={vi.fn()} showPlatform />);
    expect(screen.getByText("Facebook")).toBeInTheDocument();
  });
});

describe("VariantCard publishing", () => {
  function publication(overrides: Partial<Publication> = {}): Publication {
    return {
      id: "pub-1",
      content_item_id: "item-1",
      social_account_id: "acct-1",
      media_asset_ids: [],
      status: "succeeded",
      external_post_id: "page-1_999",
      permalink: "https://facebook.com/page-1_999",
      error: null,
      error_code: null,
      request_summary: null,
      created_at: "2026-08-10T00:00:00Z",
      completed_at: "2026-08-10T00:00:01Z",
      ...overrides,
    };
  }

  it("offers Preview only once the post is approved", () => {
    const { rerender } = render(<VariantCard item={item()} onChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();

    rerender(<VariantCard item={item({ status: "approved" })} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
  });

  it("opens the publish dialog rather than posting straight from the card", async () => {
    mockPreflight.mockResolvedValue({
      ready: true,
      blockers: [],
      warnings: [],
      platform: "facebook",
      text: "Enrol now: our courses.",
      char_count: 23,
      char_limit: 63206,
      hashtag_count: 2,
      image_id: null,
      image_required: false,
      account: null,
    });

    render(<VariantCard item={item({ status: "approved" })} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(mockPreflight).toHaveBeenCalledWith("item-1", undefined));
    // Opening the dialog must never be the thing that publishes.
    expect(mockPublish).not.toHaveBeenCalled();
  });

  it("keeps Preview disabled for a platform that is on hold", () => {
    render(
      <VariantCard
        item={item({ platform: "linkedin", status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    expect(screen.getByText(/until our LinkedIn app is verified/i)).toBeInTheDocument();
  });

  it("will not open the publish dialog for a platform on hold", () => {
    render(
      <VariantCard
        item={item({ platform: "linkedin", status: "approved" })}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockPreflight).not.toHaveBeenCalled();
  });

  it("drops every mutating action once the post is live", async () => {
    render(<VariantCard item={item({ status: "published" })} onChange={vi.fn()} />);

    // What survives: the two actions that cannot contradict the live post.
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Duplicate" })).toBeInTheDocument();
    // What must not: editing or regenerating would put our copy out of step
    // with what is already on the network, and Preview would offer to post it
    // a second time.
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();

    await waitFor(() => expect(mockFetchPublications).toHaveBeenCalledWith("item-1"));
  });

  it("links to the live post from the card header", async () => {
    mockFetchPublications.mockResolvedValue([publication()]);

    render(<VariantCard item={item({ status: "published" })} onChange={vi.fn()} />);

    expect(await screen.findByRole("link", { name: "View post ↗" })).toHaveAttribute(
      "href",
      "https://facebook.com/page-1_999",
    );
  });

  it("ignores failed attempts when looking for the live post", async () => {
    mockFetchPublications.mockResolvedValue([
      publication({ id: "pub-2", status: "failed", permalink: null }),
      publication({ id: "pub-1", permalink: "https://facebook.com/real" }),
    ]);

    render(<VariantCard item={item({ status: "published" })} onChange={vi.fn()} />);

    expect(await screen.findByRole("link", { name: "View post ↗" })).toHaveAttribute(
      "href",
      "https://facebook.com/real",
    );
  });

  it("does not ask for a permalink on a post that was never published", () => {
    render(<VariantCard item={item({ status: "approved" })} onChange={vi.fn()} />);
    expect(mockFetchPublications).not.toHaveBeenCalled();
  });
});

// Replaces navigator.clipboard, which jsdom exposes as a read-only getter.
function stubClipboard(writeText: () => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

describe("VariantCard copy button", () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("copies the whole post — body, CTA and hashtags", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);

    render(<VariantCard item={item()} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(
      "Enrol now: our courses.\n\nBook your spot.\n\n#WRCC #LearnLocal",
    );
  });

  it("copies the edited text after an edit, not the original", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);

    render(
      <VariantCard
        item={item({ body: "Enrol before Friday.", edited_body: "Enrol before Friday." })}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    await screen.findByRole("button", { name: "Copied" });
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("Enrol before Friday."),
    );
  });

  it("reports a failure instead of silently pretending it copied", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    stubClipboard(writeText);

    render(<VariantCard item={item()} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not copy to the clipboard.",
    );
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("stays available while a workflow action is in flight", () => {
    stubClipboard(vi.fn().mockResolvedValue(undefined));
    render(<VariantCard item={item()} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
  });
});
