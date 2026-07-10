import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import VariantCard from "@/components/VariantCard";
import type { ContentItem } from "@/types/content";

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
