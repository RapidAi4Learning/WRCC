import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PublishDialog from "@/components/PublishDialog";
import type { MediaAsset, ContentItem } from "@/types/content";
import type { Publication, PublishPreflight } from "@/types/publishing";

const { mockPreflight, mockPublish, mockFetchMedia } = vi.hoisted(() => ({
  mockPreflight: vi.fn(),
  mockPublish: vi.fn(),
  mockFetchMedia: vi.fn(),
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
  fetchPublishPreflight: mockPreflight,
  publishContent: mockPublish,
  fetchMedia: mockFetchMedia,
  imageFileUrl: (image: MediaAsset) => `http://api.test${image.file_url}`,
}));

// next/link needs an app-router context that vitest does not mount; the anchor
// is all these tests care about.
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

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
    generated_body: "Enrol now.",
    edited_body: null,
    body: "Enrol now.",
    hashtags: ["#WRCC", "#LearnLocal"],
    call_to_action: "Book your spot.",
    status: "approved",
    ai_metadata: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    reviewed_at: null,
    ...overrides,
  };
}

function preflight(overrides: Partial<PublishPreflight> = {}): PublishPreflight {
  return {
    ready: true,
    blockers: [],
    warnings: [],
    platform: "facebook",
    text: "Enrol now.\n\nBook your spot.\n\n#WRCC #LearnLocal",
    char_count: 48,
    char_limit: 63206,
    hashtag_count: 2,
    image_ids: [],
    image_required: false,
    max_images: 10,
    account: {
      id: "acct-1",
      platform: "facebook",
      external_id: "page-1",
      display_name: "Western Riverina Community College",
      handle: "wrcc",
      scopes: ["pages_manage_posts"],
      is_active: true,
      token_expires_at: null,
      token_expired: false,
      connected_at: "2026-08-01T00:00:00Z",
    },
    ...overrides,
  };
}

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

function image(overrides: Partial<MediaAsset> = {}): MediaAsset {
  return {
    id: "img-1",
    source: "generated",
    prompt: "Students in a classroom",
    model: "mock",
    filename: null,
    mime_type: "image/png",
    width: 1024,
    height: 1024,
    byte_size: 1024,
    alt_text: null,
    created_at: "2026-08-01T00:00:00Z",
    file_url: "/api/content/images/img-1/file",
    ...overrides,
  };
}

/** The media endpoint's shape: library plus this post's ordered selection. */
function media(library: MediaAsset[] = [], selected: string[] = []) {
  return {
    library,
    selection: selected.map((id, position) => ({
      media_asset_id: id,
      position,
      alt_text: null,
    })),
    max_images: 10,
  };
}

beforeEach(() => {
  mockPreflight.mockResolvedValue(preflight());
  mockPublish.mockResolvedValue(publication());
  mockFetchMedia.mockResolvedValue(media());
});

afterEach(() => {
  vi.clearAllMocks();
});

/** Waits for the initial preflight to land and returns the armed-state button. */
async function readyButton(name = "Publish to Facebook") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

describe("PublishDialog — what will be sent", () => {
  it("names the account the post will land on", async () => {
    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    // Twice on purpose since the preview arrived: once as the destination, and
    // once as the author in the mock-up of the post itself.
    await waitFor(() =>
      expect(
        screen.getAllByText("Western Riverina Community College"),
      ).toHaveLength(2),
    );
    expect(screen.getByText("@wrcc")).toBeInTheDocument();
  });

  it("shows the composed text from the server, not a client-side guess", async () => {
    // The backend owns composition; showing anything else would mean previewing
    // text that is not what gets posted.
    mockPreflight.mockResolvedValue(
      preflight({ text: "Server composed this exact body." }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    expect(
      await screen.findByText("Server composed this exact body."),
    ).toBeInTheDocument();
  });

  it("counts the text against the platform limit", async () => {
    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    expect(await screen.findByText(/48 \/ 63,206 characters/)).toBeInTheDocument();
    expect(screen.getByText(/2 hashtags/)).toBeInTheDocument();
  });

  it("points at Settings when no account is connected", async () => {
    mockPreflight.mockResolvedValue(
      preflight({
        ready: false,
        account: null,
        blockers: ["No Facebook account is connected."],
      }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    expect(
      await screen.findByRole("link", { name: "Connect one in Settings" }),
    ).toHaveAttribute("href", "/settings");
  });
});

describe("PublishDialog — the gate", () => {
  it("disables publishing and lists every blocker", async () => {
    mockPreflight.mockResolvedValue(
      preflight({
        ready: false,
        blockers: ["Instagram posts need an image.", "The connection expired."],
      }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    expect(await screen.findByText("Instagram posts need an image.")).toBeInTheDocument();
    expect(screen.getByText("The connection expired.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish to Facebook" })).toBeDisabled();
  });

  it("shows warnings without blocking — they are advice, not rules", async () => {
    mockPreflight.mockResolvedValue(
      preflight({ warnings: ["This post has no call to action."] }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    expect(
      await screen.findByText("This post has no call to action."),
    ).toBeInTheDocument();
    expect(await readyButton()).toBeEnabled();
  });

  it("asks for a second, explicit confirmation before sending anything", async () => {
    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    fireEvent.click(await readyButton());

    // Arming the button must not have posted anything yet.
    expect(mockPublish).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Send this to the live Facebook account now\?/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));
    await waitFor(() => expect(mockPublish).toHaveBeenCalledWith("item-1", []));
  });

  it("backs out of the confirmation without publishing", async () => {
    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Not yet" }));

    expect(mockPublish).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Publish to Facebook" }),
    ).toBeInTheDocument();
  });
});

describe("PublishDialog — the image", () => {
  it("explains that Instagram cannot go out without one", async () => {
    mockPreflight.mockResolvedValue(
      preflight({
        ready: false,
        platform: "instagram",
        image_required: true,
        blockers: ["Instagram requires an image."],
      }),
    );

    render(
      <PublishDialog
        item={item({ platform: "instagram" })}
        onClose={vi.fn()}
        onPublished={vi.fn()}
      />,
    );

    expect(await screen.findByText(/needs an image/i)).toBeInTheDocument();
  });

  it("shows the post's saved selection as already ticked", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          image({ id: "img-1", prompt: "Classroom" }),
          image({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-2"],
      ),
    );
    mockPreflight.mockResolvedValue(preflight({ image_ids: ["img-2"] }));

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Graduation" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByRole("button", { name: "Classroom" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("re-checks against the selection the operator builds", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          image({ id: "img-1", prompt: "Classroom" }),
          image({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-2"],
      ),
    );
    mockPreflight.mockResolvedValue(preflight({ image_ids: ["img-2"] }));

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Graduation" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Classroom" }));

    // Adding, not replacing: the server re-evaluates the whole set, in order.
    await waitFor(() =>
      expect(mockPreflight).toHaveBeenLastCalledWith("item-1", ["img-2", "img-1"]),
    );
  });

  it("unticking an image sends an empty selection, not the saved one", async () => {
    // The distinction the API keeps: "no images" is an instruction, and must
    // not be read as "use whatever is saved".
    mockFetchMedia.mockResolvedValue(
      media([image({ id: "img-1", prompt: "Classroom" })], ["img-1"]),
    );
    mockPreflight.mockResolvedValue(preflight({ image_ids: ["img-1"] }));

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Classroom" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Classroom" }));

    await waitFor(() =>
      expect(mockPreflight).toHaveBeenLastCalledWith("item-1", []),
    );
  });

  it("refuses to tick more images than the platform accepts", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          image({ id: "img-1", prompt: "Classroom" }),
          image({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-1"],
      ),
    );
    mockPreflight.mockResolvedValue(
      preflight({ image_ids: ["img-1"], max_images: 1 }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Graduation" })).toBeInTheDocument(),
    );
    mockPreflight.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Graduation" }));

    expect(screen.getByRole("button", { name: "Graduation" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(mockPreflight).not.toHaveBeenCalled();
  });

  it("publishes the selection in the order it was built", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          image({ id: "img-1", prompt: "Classroom" }),
          image({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-2"],
      ),
    );
    mockPreflight.mockResolvedValue(preflight({ image_ids: ["img-2"] }));

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Classroom" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Classroom" }));

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    await waitFor(() =>
      expect(mockPublish).toHaveBeenCalledWith("item-1", ["img-2", "img-1"]),
    );
  });
});

describe("PublishDialog — the outcome", () => {
  it("links to the live post once it is out", async () => {
    const onPublished = vi.fn();
    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={onPublished} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    expect(await screen.findByText("Published to Facebook.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View post ↗" })).toHaveAttribute(
      "href",
      "https://facebook.com/page-1_999",
    );
    expect(onPublished).toHaveBeenCalledOnce();
  });

  it("still reports success when the network withheld a permalink", async () => {
    // Instagram can publish and then fail the follow-up permalink lookup; the
    // post is live regardless, so this is not an error.
    mockPublish.mockResolvedValue(publication({ permalink: null }));

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    expect(await screen.findByText("Published to Facebook.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View post ↗" })).not.toBeInTheDocument();
  });

  it("treats a failed attempt as a failure even though the request returned 200", async () => {
    // The publish endpoint answers 200 with a `failed` record — reading only the
    // HTTP status here would report a post as live that never went out.
    const onPublished = vi.fn();
    mockPublish.mockResolvedValue(
      publication({
        status: "failed",
        external_post_id: null,
        permalink: null,
        error: "Session expired. Reconnect the account.",
        error_code: "reauth",
      }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={onPublished} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Session expired/);
    expect(onPublished).not.toHaveBeenCalled();
    expect(screen.queryByText("Published to Facebook.")).not.toBeInTheDocument();
    // A reauth failure is fixed in Settings, so say so.
    expect(
      screen.getByRole("link", { name: "Reconnect the account" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("locks the button when the network took a post it would not name", async () => {
    // `ambiguous` means something is probably live but we cannot link to it.
    // Preflight cannot know that — the item is still approved and every rule
    // still passes — so re-publishing must not be one click away.
    mockPublish.mockResolvedValue(
      publication({
        status: "failed",
        external_post_id: null,
        permalink: null,
        error: "Facebook accepted the post but returned no id. Check the Page.",
        error_code: "ambiguous",
      }),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Check before retrying/);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Publish to Facebook" })).toBeDisabled(),
    );
  });

  it("surfaces a refusal from the server and re-checks the post", async () => {
    const { ApiError } = await import("@/lib/api");
    mockPublish.mockRejectedValue(
      new ApiError(409, "This post has already been published."),
    );

    render(
      <PublishDialog item={item()} onClose={vi.fn()} onPublished={vi.fn()} />,
    );

    fireEvent.click(await readyButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, publish now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This post has already been published.",
    );
    await waitFor(() => expect(mockPreflight).toHaveBeenCalledTimes(2));
  });
});

describe("PublishDialog — dismissal", () => {
  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<PublishDialog item={item()} onClose={onClose} onPublished={vi.fn()} />);
    await screen.findByRole("dialog");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });
});
