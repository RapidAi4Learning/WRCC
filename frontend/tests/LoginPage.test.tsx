import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";

const { mockLogin, mockPush, mockRefresh, mockSearchParams } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockPush: vi.fn(),
  mockRefresh: vi.fn(),
  mockSearchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
  useSearchParams: () => mockSearchParams,
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
  loginSession: mockLogin,
}));

vi.mock("@/lib/auth", () => ({ setCurrentUser: vi.fn() }));

afterEach(() => {
  vi.clearAllMocks();
});

function passwordInput(): HTMLInputElement {
  return screen.getByLabelText("Password") as HTMLInputElement;
}

describe("Login — password visibility", () => {
  it("keeps the password covered until it is asked for", () => {
    render(<LoginPage />);

    expect(passwordInput()).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Show password" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reveals what was typed, and covers it again", () => {
    render(<LoginPage />);

    fireEvent.change(passwordInput(), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));

    expect(passwordInput()).toHaveAttribute("type", "text");
    expect(passwordInput()).toHaveValue("hunter2");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(passwordInput()).toHaveAttribute("type", "password");
  });

  it("does not submit the form when the password is revealed", () => {
    render(<LoginPage />);

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));

    expect(mockLogin).not.toHaveBeenCalled();
  });

  it("still submits the typed password once revealed", async () => {
    mockLogin.mockResolvedValue({ id: "u1", email: "a@b.test" });
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "a@b.test" },
    });
    fireEvent.change(passwordInput(), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(mockLogin).toHaveBeenCalledWith({
        email: "a@b.test",
        password: "hunter2",
      }),
    );
  });
});
