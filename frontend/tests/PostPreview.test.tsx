import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PostPreview from "@/components/content/PostPreview";
import type { MediaAsset } from "@/types/content";
import type { SocialAccount } from "@/types/publishing";

vi.mock("@/lib/api", () => ({
  imageFileUrl: (image: MediaAsset) => `http://api.test${image.file_url}`,
}));

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
    byte_size: 2048,
    alt_text: null,
    created_at: "2026-08-01T00:00:00Z",
    file_url: "/api/content/images/img-1/file",
    ...overrides,
  };
}

function images(count: number): MediaAsset[] {
  return Array.from({ length: count }, (_, index) =>
    image({ id: `img-${index + 1}`, file_url: `/f/${index + 1}` }),
  );
}

const account: SocialAccount = {
  id: "acct-1",
  platform: "facebook",
  external_id: "page-1",
  display_name: "Western Riverina Community College",
  handle: "wrcc",
  scopes: [],
  is_active: true,
  token_expires_at: null,
  token_expired: false,
  connected_at: "2026-08-01T00:00:00Z",
};

describe("PostPreview — the text is the server's", () => {
  it("renders exactly the text it was given, untouched", () => {
    // The single rule this component has. Recomposing here would make the
    // preview the one place in the app that can misreport what goes out.
    const exact = "Line one.\n\nBook your spot.\n\n#WRCC";

    render(
      <PostPreview
        platform="facebook"
        text={exact}
        images={[]}
        account={account}
      />,
    );

    // Split across nodes for hashtag colouring, so compare the flattened text.
    expect(screen.getByText(/Line one\./).textContent).toContain(
      "Book your spot.",
    );
    expect(screen.getByText("#WRCC")).toBeInTheDocument();
  });

  it("does not fold text that fits", () => {
    render(
      <PostPreview
        platform="instagram"
        text="Short caption."
        images={images(1)}
        account={account}
      />,
    );

    expect(screen.queryByRole("button", { name: "more" })).not.toBeInTheDocument();
  });
});

describe("PostPreview — folding", () => {
  it("folds a long caption behind Instagram's 'more' and reveals it on click", () => {
    const long = "word ".repeat(80).trim(); // ~400 chars, past Instagram's ~125

    render(
      <PostPreview
        platform="instagram"
        text={long}
        images={images(1)}
        account={account}
      />,
    );

    const more = screen.getByRole("button", { name: "more" });
    fireEvent.click(more);

    expect(screen.queryByRole("button", { name: "more" })).not.toBeInTheDocument();
  });

  it("uses each network's own fold label", () => {
    const long = "word ".repeat(200).trim();

    const { unmount } = render(
      <PostPreview platform="facebook" text={long} images={[]} account={account} />,
    );
    expect(screen.getByRole("button", { name: "See more" })).toBeInTheDocument();
    unmount();

    render(
      <PostPreview platform="linkedin" text={long} images={[]} account={account} />,
    );
    expect(screen.getByRole("button", { name: "…see more" })).toBeInTheDocument();
  });

  it("folds LinkedIn earlier than Facebook", () => {
    // 300 characters: past LinkedIn's ~200, inside Facebook's ~477.
    const text = "a".repeat(300);

    const { unmount } = render(
      <PostPreview platform="linkedin" text={text} images={[]} account={account} />,
    );
    expect(screen.getByRole("button", { name: "…see more" })).toBeInTheDocument();
    unmount();

    render(
      <PostPreview platform="facebook" text={text} images={[]} account={account} />,
    );
    expect(
      screen.queryByRole("button", { name: "See more" }),
    ).not.toBeInTheDocument();
  });
});

describe("PostPreview — Instagram", () => {
  it("shows carousel controls only when there is more than one image", () => {
    const { unmount } = render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={images(1)}
        account={account}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Next image" }),
    ).not.toBeInTheDocument();
    unmount();

    render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={images(3)}
        account={account}
      />,
    );
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("steps through the carousel in selection order", () => {
    render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={images(3)}
        account={account}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Next image" }));

    expect(screen.getByText("2/3")).toBeInTheDocument();
  });

  it("says an image is missing rather than showing an empty frame", () => {
    render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={[]}
        account={account}
      />,
    );

    expect(screen.getByText("Instagram needs an image.")).toBeInTheDocument();
  });

  it("clamps the frame to the ratio Instagram will actually allow", () => {
    // 600×1800 is 0.33 — far outside the 0.8–1.91 range, so Instagram crops it.
    // Showing the uncropped shape would preview something nobody will see.
    const { container } = render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={[image({ width: 600, height: 1800 })]}
        account={account}
      />,
    );

    const media = container.querySelector("[style*='aspect-ratio']");
    expect(media).toHaveStyle({ aspectRatio: "0.8" });
  });

  it("uses the handle as the author, since that is what Instagram shows", () => {
    render(
      <PostPreview
        platform="instagram"
        text="Caption"
        images={images(1)}
        account={account}
      />,
    );

    expect(screen.getAllByText("wrcc").length).toBeGreaterThan(0);
  });
});

describe("PostPreview — Facebook and LinkedIn", () => {
  it("shows one photo full width", () => {
    const { container } = render(
      <PostPreview
        platform="facebook"
        text="Caption"
        images={images(1)}
        account={account}
      />,
    );

    expect(container.querySelectorAll("img")).toHaveLength(1);
  });

  it("counts the photos it could not fit in the mosaic", () => {
    // Six images: a lead, three cells, and "+2" on the last one.
    render(
      <PostPreview
        platform="facebook"
        text="Caption"
        images={images(6)}
        account={account}
      />,
    );

    expect(screen.getByText("+2")).toBeInTheDocument();
  });

  it("falls back to a placeholder name when nothing is connected yet", () => {
    render(
      <PostPreview platform="linkedin" text="Caption" images={[]} account={null} />,
    );

    expect(screen.getByText("Your WRCC account")).toBeInTheDocument();
  });

  it("labels itself as approximate, so it is not read as a guarantee", () => {
    render(
      <PostPreview
        platform="facebook"
        text="Caption"
        images={[]}
        account={account}
      />,
    );

    expect(screen.getByText(/Approximate preview/)).toBeInTheDocument();
  });
});
