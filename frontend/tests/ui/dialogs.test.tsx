import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog, PromptDialog } from "@/components/ui";

describe("ConfirmDialog", () => {
  function renderConfirm() {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        title="Disconnect this account?"
        confirmLabel="Disconnect"
        tone="danger"
        onConfirm={onConfirm}
        onCancel={onCancel}
      >
        <p>Posts already published stay live.</p>
      </ConfirmDialog>,
    );
    return { onConfirm, onCancel };
  }

  it("states the question and starts focus on Cancel, not on the risky action", () => {
    renderConfirm();
    expect(screen.getByRole("dialog", { name: "Disconnect this account?" })).toHaveTextContent(
      "Posts already published stay live.",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("confirms only on the confirm button", () => {
    const { onConfirm, onCancel } = renderConfirm();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("treats Escape as cancel", () => {
    const { onConfirm, onCancel } = renderConfirm();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("PromptDialog", () => {
  function renderPrompt() {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(
      <PromptDialog
        title="Reject this post?"
        label="Reason"
        confirmLabel="Reject post"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );
    return { onSubmit, onCancel };
  }

  it("focuses the text field and marks it optional", () => {
    renderPrompt();
    expect(screen.getByLabelText(/Reason/)).toHaveFocus();
    expect(screen.getByText("(optional)")).toBeInTheDocument();
  });

  it("submits the trimmed text", () => {
    const { onSubmit } = renderPrompt();
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "  Wrong date.  " } });
    fireEvent.click(screen.getByRole("button", { name: "Reject post" }));
    expect(onSubmit).toHaveBeenCalledWith("Wrong date.");
  });

  it("submits an empty string when left blank", () => {
    const { onSubmit } = renderPrompt();
    fireEvent.click(screen.getByRole("button", { name: "Reject post" }));
    expect(onSubmit).toHaveBeenCalledWith("");
  });

  it("cancels without submitting", () => {
    const { onSubmit, onCancel } = renderPrompt();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
