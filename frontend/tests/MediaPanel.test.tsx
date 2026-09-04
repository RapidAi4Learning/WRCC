import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MediaPanel from "@/components/MediaPanel";
import type { MediaAsset } from "@/types/content";

const {
  mockFetchMedia,
  mockUpload,
  mockSaveSelection,
  mockGenerate,
  mockSuggestions,
  mockDelete,
} = vi.hoisted(() => ({
  mockFetchMedia: vi.fn(),
  mockUpload: vi.fn(),
  mockSaveSelection: vi.fn(),
  mockGenerate: vi.fn(),
  mockSuggestions: vi.fn(),
  mockDelete: vi.fn(),
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
  fetchMedia: mockFetchMedia,
  uploadMedia: mockUpload,
  saveMediaSelection: mockSaveSelection,
  generateImage: mockGenerate,
  fetchImageSuggestions: mockSuggestions,
  deleteMediaAsset: mockDelete,
  imageFileUrl: (image: MediaAsset) => `http://api.test${image.file_url}`,
}));

function asset(overrides: Partial<MediaAsset> = {}): MediaAsset {
  return {
    id: "img-1",
    source: "generated",
    prompt: "Students in a classroom",
    model: "mock",
    filename: null,
    mime_type: "image/png",
    width: 1024,
    height: 1024,
    byte_size: 2048,
    alt_text: null,
    created_at: "2026-08-01T00:00:00Z",
    file_url: "/api/content/images/img-1/file",
    ...overrides,
  };
}

function media(library: MediaAsset[] = [], selected: string[] = [], max = 10) {
  return {
    library,
    selection: selected.map((id, position) => ({
      media_asset_id: id,
      position,
      alt_text: null,
    })),
    max_images: max,
  };
}

function pngFile(name = "photo.png", size = 1000): File {
  const file = new File([new Uint8Array(size)], name, { type: "image/png" });
  // jsdom does not enforce size from the blob parts.
  Object.defineProperty(file, "size", { value: size });
  return file;
}

beforeEach(() => {
  mockFetchMedia.mockResolvedValue(media());
  mockSuggestions.mockResolvedValue({ prompts: ["A bright classroom"] });
  mockSaveSelection.mockImplementation((_item, ids: string[]) =>
    Promise.resolve({
      selection: ids.map((id, position) => ({
        media_asset_id: id,
        position,
        alt_text: null,
      })),
      warnings: [],
    }),
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

/** Opens the dialog and waits for the first media load to land. */
async function open() {
  const result = render(<MediaPanel itemId="item-1" />);
  const toggle = await screen.findByRole("button", { name: /Media/ });
  fireEvent.click(toggle);
  await screen.findByRole("dialog", { name: "Post media" });
  return result;
}

describe("MediaPanel — generate and upload are separate actions", () => {
  it("offers both, with Generate open first", async () => {
    await open();

    // The client's actual request: these must not be the same button.
    const generate = screen.getByRole("tab", { name: /Generate with AI/ });
    const upload = screen.getByRole("tab", { name: /Upload files/ });
    expect(generate).toHaveAttribute("aria-selected", "true");
    expect(upload).toHaveAttribute("aria-selected", "false");
  });

  it("swaps to the upload controls without touching the generator", async () => {
    await open();

    fireEvent.click(screen.getByRole("tab", { name: /Upload files/ }));

    expect(screen.getByRole("button", { name: "Choose files" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Generate image" }),
    ).not.toBeInTheDocument();
  });

  it("generates from the prompt and re-reads what the server did", async () => {
    mockGenerate.mockResolvedValue(asset());
    await open();

    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "A bright classroom" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate image" }));

    await waitFor(() =>
      expect(mockGenerate).toHaveBeenCalledWith("item-1", "A bright classroom"),
    );
    // Re-read rather than splice: the server also attaches the new asset, and
    // guessing at that is how the panel would drift from the post.
    await waitFor(() => expect(mockFetchMedia).toHaveBeenCalledTimes(2));
  });
});

describe("MediaPanel — uploading", () => {
  it("sends the chosen files", async () => {
    mockUpload.mockResolvedValue([asset({ id: "img-9", source: "uploaded" })]);
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /Upload files/ }));

    const input = screen.getByLabelText("Upload images");
    fireEvent.change(input, { target: { files: [pngFile()] } });

    await waitFor(() =>
      expect(mockUpload).toHaveBeenCalledWith("item-1", [
        expect.objectContaining({ name: "photo.png" }),
      ]),
    );
  });

  it("skips a file of the wrong type and names it", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /Upload files/ }));

    fireEvent.change(screen.getByLabelText("Upload images"), {
      target: {
        files: [new File(["x"], "notes.pdf", { type: "application/pdf" })],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("notes.pdf");
    expect(mockUpload).not.toHaveBeenCalled();
  });

  it("skips an oversized file without abandoning the rest", async () => {
    mockUpload.mockResolvedValue([asset({ id: "img-9" })]);
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /Upload files/ }));

    fireEvent.change(screen.getByLabelText("Upload images"), {
      target: {
        files: [pngFile("huge.png", 20 * 1024 * 1024), pngFile("ok.png")],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("huge.png");
    await waitFor(() =>
      expect(mockUpload).toHaveBeenCalledWith("item-1", [
        expect.objectContaining({ name: "ok.png" }),
      ]),
    );
  });

  it("says that uploads are stripped, because that is not obvious", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /Upload files/ }));

    expect(screen.getByText(/metadata .* is stripped/i)).toBeInTheDocument();
  });
});

describe("MediaPanel — the selection is the post", () => {
  it("badges each library tile with where it came from", async () => {
    mockFetchMedia.mockResolvedValue(
      media([
        asset({ id: "img-1" }),
        asset({ id: "img-2", source: "uploaded", prompt: null, filename: "mine.jpg" }),
      ]),
    );
    await open();

    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByText("Uploaded")).toBeInTheDocument();
  });

  it("saves a tick immediately, in the order ticked", async () => {
    mockFetchMedia.mockResolvedValue(
      media([
        asset({ id: "img-1", prompt: "Classroom" }),
        asset({ id: "img-2", prompt: "Graduation" }),
      ]),
    );
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Graduation" }));
    await waitFor(() =>
      expect(mockSaveSelection).toHaveBeenLastCalledWith("item-1", ["img-2"], false),
    );

    fireEvent.click(screen.getByRole("button", { name: "Classroom" }));
    await waitFor(() =>
      expect(mockSaveSelection).toHaveBeenLastCalledWith(
        "item-1",
        ["img-2", "img-1"],
        false,
      ),
    );
  });

  it("refuses to go past the platform ceiling and says why", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          asset({ id: "img-1", prompt: "Classroom" }),
          asset({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-1"],
        1,
      ),
    );
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Graduation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("at most 1");
    expect(mockSaveSelection).not.toHaveBeenCalled();
  });

  it("reorders the selection with the arrow controls", async () => {
    mockFetchMedia.mockResolvedValue(
      media(
        [
          asset({ id: "img-1", prompt: "Classroom" }),
          asset({ id: "img-2", prompt: "Graduation" }),
        ],
        ["img-1", "img-2"],
      ),
    );
    await open();

    fireEvent.click(
      screen.getByRole("button", { name: "Move Graduation earlier" }),
    );

    await waitFor(() =>
      expect(mockSaveSelection).toHaveBeenLastCalledWith(
        "item-1",
        ["img-2", "img-1"],
        false,
      ),
    );
  });

  it("copies the selection to the other platforms on request", async () => {
    // The "Facebook and Instagram must match" case, as an action rather than a
    // rule — so LinkedIn can still be given something different afterwards.
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })], ["img-1"]),
    );
    await open();

    fireEvent.click(
      screen.getByRole("button", { name: "Use on other platforms" }),
    );

    await waitFor(() =>
      expect(mockSaveSelection).toHaveBeenCalledWith("item-1", ["img-1"], true),
    );
  });

  it("reports a sibling it could not update instead of staying quiet", async () => {
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })], ["img-1"]),
    );
    mockSaveSelection.mockResolvedValue({
      selection: [{ media_asset_id: "img-1", position: 0, alt_text: null }],
      warnings: ["Instagram accepts at most 10 images, so its selection was left alone."],
    });
    await open();

    fireEvent.click(
      screen.getByRole("button", { name: "Use on other platforms" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "left alone",
    );
  });

  it("rolls back an optimistic tick when the save fails", async () => {
    // The strip must never claim a selection the server did not accept.
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })]),
    );
    mockSaveSelection.mockRejectedValue(new Error("network down"));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Classroom" }));

    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Classroom" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("says plainly when a post is going out with no images at all", async () => {
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })]),
    );
    await open();

    expect(
      screen.getByText(/this post will go out as text only/i),
    ).toBeInTheDocument();
  });

  it("counts the selection against the platform ceiling", async () => {
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1" }), asset({ id: "img-2" })], ["img-1"], 10),
    );
    await open();

    expect(screen.getByText("In this post (1/10)")).toBeInTheDocument();
  });
});

describe("MediaPanel — the library is shared", () => {
  it("says the library spans the whole generation", async () => {
    mockFetchMedia.mockResolvedValue(media([asset()]));
    await open();

    expect(
      screen.getByText(/Shared with the other platforms in this generation/),
    ).toBeInTheDocument();
  });

  it("deletes an asset and re-reads the library", async () => {
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })]),
    );
    mockDelete.mockResolvedValue(undefined);
    await open();

    const tile = screen.getByRole("button", { name: "Classroom" }).closest("li");
    fireEvent.click(within(tile as HTMLElement).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("img-1"));
    await waitFor(() => expect(mockFetchMedia).toHaveBeenCalledTimes(2));
  });

  it("surfaces the server's refusal to delete a published image", async () => {
    mockFetchMedia.mockResolvedValue(
      media([asset({ id: "img-1", prompt: "Classroom" })]),
    );
    const { ApiError } = await import("@/lib/api");
    mockDelete.mockRejectedValue(
      new (ApiError as unknown as new (s: number, m: string) => Error)(
        409,
        "This image has been published.",
      ),
    );
    await open();

    const tile = screen.getByRole("button", { name: "Classroom" }).closest("li");
    fireEvent.click(within(tile as HTMLElement).getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This image has been published.",
    );
  });
});
