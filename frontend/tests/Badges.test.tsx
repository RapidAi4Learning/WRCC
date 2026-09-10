import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlatformBadge, StatusBadge } from "@/components/content/Badges";

describe("badges", () => {
  it("labels every platform", () => {
    render(
      <>
        <PlatformBadge platform="facebook" />
        <PlatformBadge platform="instagram" />
        <PlatformBadge platform="linkedin" />
      </>,
    );
    expect(screen.getByText("Facebook")).toBeInTheDocument();
    expect(screen.getByText("Instagram")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn")).toBeInTheDocument();
  });

  it("labels workflow statuses", () => {
    render(
      <>
        <StatusBadge status="draft" />
        <StatusBadge status="pending_approval" />
        <StatusBadge status="approved" />
      </>,
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("Pending approval")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });
});
