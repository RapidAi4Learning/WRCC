import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GeneratePage from "@/app/(app)/generate/page";

const { mockGenerate } = vi.hoisted(() => ({ mockGenerate: vi.fn() }));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  },
  generateContent: mockGenerate,
  fetchCourses: vi.fn().mockResolvedValue([]),
}));

const SPEED_STORAGE_KEY = "wrcc.generate.speed";

beforeEach(() => {
  mockGenerate.mockReset().mockResolvedValue({
    generation_group: "group-1",
    items: [],
    warnings: [],
  });
  window.localStorage.clear();
});

async function generate(): Promise<Record<string, unknown>> {
  fireEvent.change(screen.getByLabelText(/free topic/), {
    target: { value: "Spring first aid enrolments" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Generate 3 ideas/ }));
  await waitFor(() => expect(mockGenerate).toHaveBeenCalledTimes(1));
  return mockGenerate.mock.calls[0][0];
}

describe("Generate — writing speed", () => {
  it("offers three speeds, with Balanced chosen by default", () => {
    render(<GeneratePage />);

    const group = screen.getByRole("radiogroup", { name: /Writing speed/ });
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("radio", { name: /Balanced/ })).toBeChecked();
  });

  it("sends Balanced as the low effort when the choice is left alone", async () => {
    render(<GeneratePage />);

    expect((await generate()).reasoning_effort).toBe("low");
  });

  it("sends the speed the person picked", async () => {
    render(<GeneratePage />);
    fireEvent.click(screen.getByRole("radio", { name: /Best quality/ }));

    expect((await generate()).reasoning_effort).toBe("medium");
  });

  it("remembers the last speed on this device", async () => {
    window.localStorage.setItem(SPEED_STORAGE_KEY, "minimal");

    render(<GeneratePage />);

    await waitFor(() => expect(screen.getByRole("radio", { name: /Fast/ })).toBeChecked());
  });

  it("stores a new choice for next time", () => {
    render(<GeneratePage />);
    fireEvent.click(screen.getByRole("radio", { name: /Fast/ }));

    expect(window.localStorage.getItem(SPEED_STORAGE_KEY)).toBe("minimal");
  });

  it("ignores a stored value it does not offer", async () => {
    // e.g. left over from an older version, or edited by hand.
    window.localStorage.setItem(SPEED_STORAGE_KEY, "high");

    render(<GeneratePage />);

    expect(screen.getByRole("radio", { name: /Balanced/ })).toBeChecked();
    expect((await generate()).reasoning_effort).toBe("low");
  });
});
