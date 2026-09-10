import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SyncReviewPanel from "@/components/catalog/SyncReviewPanel";
import type { Changeset, SyncRun } from "@/types/course";

function run(changeset: Changeset, overrides: Partial<SyncRun> = {}): SyncRun {
  return {
    id: "run-1",
    status: "pending",
    courses_found: 42,
    offerings_found: 187,
    changeset,
    error: null,
    started_at: "2026-09-02T01:00:00Z",
    finished_at: "2026-09-02T01:00:38Z",
    reviewed_at: null,
    created_at: "2026-09-02T01:00:00Z",
    ...overrides,
  };
}

function renderPanel(
  changeset: Changeset,
  overrides: {
    isBusy?: boolean;
    courseTitles?: Record<string, string>;
    onApprove?: () => void;
    onReject?: (reason?: string) => void;
    runOverrides?: Partial<SyncRun>;
  } = {},
) {
  const onApprove = overrides.onApprove ?? vi.fn();
  const onReject = overrides.onReject ?? vi.fn();
  render(
    <SyncReviewPanel
      run={run(changeset, overrides.runOverrides)}
      isBusy={overrides.isBusy ?? false}
      courseTitles={overrides.courseTitles ?? {}}
      onApprove={onApprove}
      onReject={onReject}
    />,
  );
  return { onApprove, onReject };
}

function section(title: string): HTMLElement {
  return screen.getByText(title).closest("details") as HTMLElement;
}

describe("SyncReviewPanel", () => {
  it("leads with the number of changes, not the crawl size", () => {
    renderPanel({
      courses_added: [
        {
          course_code: "WHS101",
          title: "Work Health & Safety",
          category: "Safety",
          description: null,
          is_accredited: true,
          source_url: null,
          offerings: [],
        },
      ],
      offerings_removed: ["9001"],
    });

    expect(
      screen.getByRole("heading", { name: "2 changes staged" }),
    ).toBeInTheDocument();
    // The crawl totals stay, demoted to context about how the run went.
    expect(screen.getByText(/Crawled 42 courses · 187 dates/)).toBeInTheDocument();
  });

  it("tallies only the categories that actually changed", () => {
    renderPanel({
      courses_added: [
        {
          course_code: "WHS101",
          title: "Work Health & Safety",
          category: null,
          description: null,
          is_accredited: false,
          source_url: null,
          offerings: [],
        },
      ],
    });

    expect(screen.getByText("new course")).toBeInTheDocument();
    expect(screen.queryByText(/courses to deactivate/)).not.toBeInTheDocument();
    expect(screen.queryByText(/dates updated/)).not.toBeInTheDocument();
  });

  it("names the course a new date belongs to", () => {
    renderPanel(
      {
        offerings_added: [
          {
            offering_code: "9002",
            course_code: "HLTAID011",
            price: 185,
            location: "WRCC Griffith",
            start_date: "2026-08-07",
            finish_date: "2026-08-07",
            places_available: 5,
          },
        ],
      },
      { courseTitles: { HLTAID011: "Provide First Aid" } },
    );

    const added = section("New course dates");
    expect(within(added).getByText("Provide First Aid")).toBeInTheDocument();
    expect(
      within(added).getByText(/7 Aug 2026 · WRCC Griffith · \$185\.00 · 5 places/),
    ).toBeInTheDocument();
  });

  it("shows a field-level before and after for an update", () => {
    renderPanel({
      offerings_updated: [
        {
          offering_code: "111",
          course_code: "HLTAID011",
          changes: {
            price: { from: 185, to: 195 },
            start_date: { from: "2026-08-07", to: "2026-09-04" },
          },
        },
      ],
    });

    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("$185.00")).toBeInTheDocument();
    expect(screen.getByText("$195.00")).toBeInTheDocument();
    expect(screen.getByText("Starts")).toBeInTheDocument();
    expect(screen.getByText("7 Aug 2026")).toBeInTheDocument();
    // ICU spells the short month "Sep" or "Sept" depending on the version.
    expect(screen.getByText(/^4 Sept? 2026$/)).toBeInTheDocument();
  });

  it("warns that removals only deactivate, and names what goes dark", () => {
    renderPanel({
      courses_removed: [
        {
          course_code: "HLTAID011",
          title: "Provide First Aid",
          category: "First Aid",
          offerings_affected: 3,
        },
      ],
    });

    expect(screen.getByText(/Removals in this changeset/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is deleted/)).toBeInTheDocument();

    const removed = section("Courses to deactivate");
    expect(within(removed).getByText("Provide First Aid")).toBeInTheDocument();
    expect(
      within(removed).getByText(/First Aid · 3 scheduled dates go with it/),
    ).toBeInTheDocument();
  });

  it("still renders a changeset staged before removals carried context", () => {
    renderPanel({ courses_removed: ["HLTAID011"] }, {
      courseTitles: { HLTAID011: "Provide First Aid" },
    });

    const removed = section("Courses to deactivate");
    expect(within(removed).getByText("HLTAID011")).toBeInTheDocument();
    expect(within(removed).getByText("Provide First Aid")).toBeInTheDocument();
  });

  it("says on the button exactly how much is being applied", () => {
    const { onApprove } = renderPanel({
      courses_updated: [
        { course_code: "A", changes: { title: { from: "Old", to: "New" } } },
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve & apply 1 change" }));
    // Nothing was unticked, so this is the same request as before selection.
    expect(onApprove).toHaveBeenCalledWith(undefined);
  });

  it("treats an empty changeset as a no-op rather than an approval", () => {
    renderPanel({ summary: undefined });

    expect(
      screen.getByRole("heading", {
        name: "No changes — the site already matches this catalog",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close out this run" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("asks for a reason in the page instead of a browser prompt", () => {
    const { onReject } = renderPanel({ courses_removed: ["A"] });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByLabelText(/Why are you discarding/), {
      target: { value: "prices look wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Discard changeset" }));

    expect(onReject).toHaveBeenCalledWith("prices look wrong");
  });

  it("sends no reason when the operator leaves it blank", () => {
    const { onReject } = renderPanel({ courses_removed: ["A"] });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard changeset" }));

    expect(onReject).toHaveBeenCalledWith(undefined);
  });

  it("backs out of rejecting without discarding anything", () => {
    const { onReject } = renderPanel({ courses_removed: ["A"] });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));

    expect(onReject).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("holds a long section back behind one click so the actions stay reachable", () => {
    const many = Array.from({ length: 30 }, (_, index) => ({
      course_code: `C${index}`,
      title: `Course ${index}`,
      category: null,
      description: null,
      is_accredited: false,
      source_url: null,
      offerings: [],
    }));
    renderPanel({ courses_added: many });

    expect(screen.getByText("Course 0")).toBeInTheDocument();
    expect(screen.queryByText("Course 20")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show the remaining 18" }));
    expect(screen.getByText("Course 20")).toBeInTheDocument();
  });

  it("locks both decisions while a request is in flight", () => {
    renderPanel({ courses_removed: ["A"] }, { isBusy: true });

    expect(screen.getByRole("button", { name: /Approve & apply/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });
});

describe("SyncReviewPanel selection", () => {
  const twoCourses: Changeset = {
    courses_added: [
      {
        course_code: "WHS101",
        title: "Work Health & Safety",
        category: null,
        description: null,
        is_accredited: false,
        source_url: null,
        offerings: [],
      },
      {
        course_code: "WHS102",
        title: "Working at Heights",
        category: null,
        description: null,
        is_accredited: false,
        source_url: null,
        offerings: [],
      },
    ],
  };

  function tick(name: string): HTMLElement {
    return screen.getByRole("checkbox", { name });
  }

  it("starts with every change ticked", () => {
    renderPanel(twoCourses);

    expect(tick("Apply WHS101 — Work Health & Safety")).toBeChecked();
    expect(tick("Apply WHS102 — Working at Heights")).toBeChecked();
  });

  it("sends only the unticked codes to the server", () => {
    const { onApprove } = renderPanel(twoCourses);

    fireEvent.click(tick("Apply WHS102 — Working at Heights"));
    fireEvent.click(screen.getByRole("button", { name: /Approve & apply/ }));

    expect(onApprove).toHaveBeenCalledWith({ courses_added: ["WHS102"] });
  });

  it("counts what will actually be applied on the button", () => {
    renderPanel(twoCourses);

    fireEvent.click(tick("Apply WHS102 — Working at Heights"));
    expect(
      screen.getByRole("button", { name: "Approve & apply 1 of 2 changes" }),
    ).toBeInTheDocument();
  });

  it("explains that a skipped change comes back on the next sync", () => {
    renderPanel(twoCourses);

    expect(screen.queryByText(/stages it again/)).not.toBeInTheDocument();
    fireEvent.click(tick("Apply WHS101 — Work Health & Safety"));
    expect(screen.getByText(/1 change stays as/)).toBeInTheDocument();
    expect(screen.getByText(/stages it again/)).toBeInTheDocument();
  });

  it("re-ticks a change that was unticked by mistake", () => {
    const { onApprove } = renderPanel(twoCourses);
    const box = tick("Apply WHS102 — Working at Heights");

    fireEvent.click(box);
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: /Approve & apply/ }));

    expect(onApprove).toHaveBeenCalledWith(undefined);
  });

  it("drops a whole section in one click, and puts it back", () => {
    const { onApprove } = renderPanel(twoCourses);

    fireEvent.click(screen.getByRole("button", { name: "Skip all" }));
    expect(tick("Apply WHS101 — Work Health & Safety")).not.toBeChecked();
    expect(tick("Apply WHS102 — Working at Heights")).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Include all" }));
    fireEvent.click(screen.getByRole("button", { name: /Approve & apply/ }));
    expect(onApprove).toHaveBeenCalledWith(undefined);
  });

  it("points at Reject rather than approving nothing", () => {
    renderPanel(twoCourses);

    fireEvent.click(screen.getByRole("button", { name: "Skip all" }));

    expect(screen.getByRole("button", { name: /Approve & apply/ })).toBeDisabled();
    expect(screen.getByText(/Nothing is ticked/)).toBeInTheDocument();
  });

  it("goes quiet about removals once they are all unticked", () => {
    renderPanel({
      courses_removed: [
        {
          course_code: "HLTAID011",
          title: "Provide First Aid",
          category: null,
          offerings_affected: 0,
        },
      ],
    });

    expect(screen.getByText(/Removals in this changeset/)).toBeInTheDocument();
    fireEvent.click(tick("Apply HLTAID011 — Provide First Aid"));
    expect(screen.queryByText(/Removals in this changeset/)).not.toBeInTheDocument();
  });

  it("keys a date row by its own code, not by the course it hangs off", () => {
    // Two dates on one course: unticking one must not take the other with it.
    const { onApprove } = renderPanel(
      {
        offerings_removed: [
          {
            offering_code: "9001",
            course_code: "HLTAID011",
            start_date: "2026-08-07",
            location: "Griffith",
            price: null,
          },
          {
            offering_code: "9002",
            course_code: "HLTAID011",
            start_date: "2026-09-04",
            location: "Leeton",
            price: null,
          },
        ],
      },
      { courseTitles: { HLTAID011: "Provide First Aid" } },
    );

    const boxes = screen.getAllByRole("checkbox", {
      name: "Apply HLTAID011 — Provide First Aid",
    });
    expect(boxes).toHaveLength(2);

    fireEvent.click(boxes[0]);
    expect(boxes[1]).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /Approve & apply/ }));
    expect(onApprove).toHaveBeenCalledWith({ offerings_removed: ["9001"] });
  });
});
