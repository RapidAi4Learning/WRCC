import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppHeader from "@/components/layout/AppHeader";
import UserMenu from "@/components/layout/UserMenu";
import { initials } from "@/lib/initials";

const { mockPush, mockLogout, mockGetCurrentUser, pathname } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockLogout: vi.fn(),
  mockGetCurrentUser: vi.fn(),
  pathname: { current: "/history" },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, refresh: vi.fn() }),
  usePathname: () => pathname.current,
}));

vi.mock("@/lib/auth", () => ({
  getCurrentUser: mockGetCurrentUser,
  logout: mockLogout,
}));

const USER = {
  id: "user-1",
  email: "alex.smith@wrcc.nsw.edu.au",
  display_name: "Alex Smith",
};

beforeEach(() => {
  mockPush.mockReset();
  mockLogout.mockReset().mockResolvedValue(undefined);
  mockGetCurrentUser.mockReset().mockResolvedValue(USER);
  pathname.current = "/history";
});

describe("initials", () => {
  it("takes the first letters of up to two words, email local parts included", () => {
    expect(initials("Western Riverina Community College")).toBe("WR");
    expect(initials("alex.smith")).toBe("AS");
    expect(initials("")).toBe("");
  });
});

describe("UserMenu", () => {
  it("shows the user's initials and names the account on the trigger", async () => {
    render(<UserMenu />);
    expect(
      await screen.findByRole("button", { name: `Account: ${USER.email}` }),
    ).toHaveTextContent("AS");
  });

  it("opens a menu with the email and focuses Log out; Escape closes it", async () => {
    render(<UserMenu />);
    const trigger = await screen.findByRole("button", { name: /Account/ });
    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toHaveTextContent(USER.email);
    expect(screen.getByRole("menuitem", { name: "Log out" })).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("logs out and goes back to the login page", async () => {
    render(<UserMenu />);
    fireEvent.click(await screen.findByRole("button", { name: /Account/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Log out" }));

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/login"));
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("closes on a click outside", async () => {
    render(<UserMenu />);
    fireEvent.click(await screen.findByRole("button", { name: /Account/ }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("AppHeader", () => {
  it("marks the current page in the navigation", () => {
    render(<AppHeader />);
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Generate" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("folds the navigation behind a menu button that reports its state", () => {
    render(<AppHeader />);
    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "main-navigation");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("shows the official logo", () => {
    render(<AppHeader />);
    expect(
      screen.getByRole("img", { name: "Western Riverina Community College" }),
    ).toBeInTheDocument();
  });
});
