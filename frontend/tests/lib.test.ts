import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { cx } from "@/lib/cx";
import { errorMessage } from "@/lib/errors";
import { PLATFORMS, PLATFORM_LABELS, STATUSES, STATUS_LABELS } from "@/lib/platforms";
import { moveItem, toggleOrdered } from "@/lib/selection";

describe("cx", () => {
  it("joins truthy class names and drops the rest", () => {
    expect(cx("a", false, null, undefined, "", "b")).toBe("a b");
  });
});

describe("errorMessage", () => {
  it("uses the server's detail for an ApiError", () => {
    expect(errorMessage(new ApiError(409, "Already published."), "Failed.")).toBe(
      "Already published.",
    );
  });

  it("falls back for anything else, so raw exception text never reaches the screen", () => {
    expect(errorMessage(new TypeError("fetch failed"), "Failed.")).toBe("Failed.");
    expect(errorMessage("boom", "Failed.")).toBe("Failed.");
  });
});

describe("platforms", () => {
  it("labels every platform and status it lists", () => {
    for (const platform of PLATFORMS) expect(PLATFORM_LABELS[platform]).toBeTruthy();
    for (const status of STATUSES) expect(STATUS_LABELS[status]).toBeTruthy();
  });
});

describe("toggleOrdered", () => {
  it("appends a new id at the end, keeping tick order", () => {
    expect(toggleOrdered(["a"], "b", 3)).toEqual({ list: ["a", "b"], isOverLimit: false });
  });

  it("removes an id that is already selected", () => {
    expect(toggleOrdered(["a", "b"], "a", 3)).toEqual({ list: ["b"], isOverLimit: false });
  });

  it("refuses to pass the ceiling and says so", () => {
    expect(toggleOrdered(["a", "b"], "c", 2)).toEqual({ list: ["a", "b"], isOverLimit: true });
  });

  it("still allows removal when the list is full", () => {
    expect(toggleOrdered(["a", "b"], "b", 2)).toEqual({ list: ["a"], isOverLimit: false });
  });

  it("never mutates its input", () => {
    const original = ["a"];
    toggleOrdered(original, "b", 5);
    expect(original).toEqual(["a"]);
  });
});

describe("moveItem", () => {
  it("swaps with the neighbour in the given direction", () => {
    expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
  });

  it("returns an unchanged copy when the move would leave the list", () => {
    const original = ["a", "b"];
    const moved = moveItem(original, 0, -1);
    expect(moved).toEqual(["a", "b"]);
    expect(moved).not.toBe(original);
  });
});
