import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "@/components/ui";

function renderModal(onClose = vi.fn()) {
  const result = render(
    <Modal title="Post media" hint="Pick images." onClose={onClose}>
      <button type="button">First action</button>
      <button type="button">Last action</button>
    </Modal>,
  );
  return { onClose, ...result };
}

describe("Modal", () => {
  it("is a dialog named by its title", () => {
    renderModal();
    expect(screen.getByRole("dialog", { name: "Post media" })).toBeInTheDocument();
    expect(screen.getByText("Pick images.")).toBeInTheDocument();
  });

  it("closes on Escape, on the close button and on a backdrop click", () => {
    const { onClose } = renderModal();
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("does not close on a click inside the dialog", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "First action" }));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("locks the page scroll while open and restores it on close", () => {
    document.body.style.overflow = "auto";
    const { unmount } = renderModal();
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("auto");
  });

  it("takes focus on open and hands it back to the opener on close", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = renderModal();
    expect(screen.getByRole("dialog")).toHaveFocus();

    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("keeps Tab inside the dialog", () => {
    renderModal();
    const close = screen.getByRole("button", { name: "Close" });
    const last = screen.getByRole("button", { name: "Last action" });

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("closes only the topmost of two stacked dialogs on Escape", () => {
    const outerClose = vi.fn();

    function Stack() {
      const [isInnerOpen, setIsInnerOpen] = useState(true);
      return (
        <Modal title="Outer" onClose={outerClose}>
          {isInnerOpen ? (
            <Modal title="Inner" onClose={() => setIsInnerOpen(false)}>
              <p>inner body</p>
            </Modal>
          ) : null}
        </Modal>
      );
    }

    render(<Stack />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Inner" })).not.toBeInTheDocument();
    expect(outerClose).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(outerClose).toHaveBeenCalledTimes(1);
  });
});
