import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/(app)/settings/page";
import type { SocialAccount } from "@/types/publishing";

const {
  mockActivate,
  mockDisconnect,
  mockFetchAccounts,
  mockAuthorizeUrl,
  mockVerify,
} = vi.hoisted(() => ({
  mockActivate: vi.fn(),
  mockDisconnect: vi.fn(),
  mockFetchAccounts: vi.fn(),
  mockAuthorizeUrl: vi.fn(),
  mockVerify: vi.fn(),
}));

let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
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
  activateSocialAccount: mockActivate,
  disconnectSocialAccount: mockDisconnect,
  fetchSocialAccounts: mockFetchAccounts,
  fetchAuthorizeUrl: mockAuthorizeUrl,
  verifySocialAccount: mockVerify,
}));

function account(overrides: Partial<SocialAccount> = {}): SocialAccount {
  return {
    id: "acct-1",
    platform: "facebook",
    external_id: "page-1",
    display_name: "Western Riverina Community College",
    handle: null,
    scopes: ["pages_manage_posts"],
    is_active: true,
    token_expires_at: null,
    token_expired: false,
    connected_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString();
}

beforeEach(() => {
  searchParams = new URLSearchParams();
  mockFetchAccounts.mockResolvedValue([]);
  mockAuthorizeUrl.mockResolvedValue({
    provider: "meta",
    authorize_url: "https://facebook.test/dialog?state=abc",
  });
  mockActivate.mockResolvedValue(account());
  mockDisconnect.mockResolvedValue(undefined);
  // jsdom's navigation is not implemented; replace it so "Connect" is testable.
  Object.defineProperty(window, "location", {
    value: { assign: vi.fn(), href: "http://localhost/settings" },
    writable: true,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Settings — connections", () => {
  it("shows a card per network, all disconnected initially", async () => {
    render(<SettingsPage />);

    expect(
      await screen.findByRole("button", { name: "Connect Facebook" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Connect Instagram" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Connect LinkedIn" }),
    ).toBeInTheDocument();
  });

  it("will not let an operator connect a network we cannot post to", async () => {
    render(<SettingsPage />);

    const linkedin = await screen.findByRole("button", {
      name: "Connect LinkedIn",
    });
    expect(linkedin).toBeDisabled();
    // The reason sits on the card, and the button points at it.
    expect(
      screen.getByText(/LinkedIn publishing is on hold/i),
    ).toBeInTheDocument();
    expect(linkedin).toHaveAccessibleDescription(
      /LinkedIn publishing is on hold/i,
    );
  });

  it("leaves the networks we are cleared for alone", async () => {
    render(<SettingsPage />);

    expect(
      await screen.findByRole("button", { name: "Connect Facebook" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Connect Instagram" }),
    ).toBeEnabled();
  });

  it("keeps an already-connected held account manageable", async () => {
    mockFetchAccounts.mockResolvedValue([
      account({ platform: "linkedin", display_name: "WRCC Page" }),
    ]);

    render(<SettingsPage />);

    // Reconnect is held shut, but nothing strands the existing connection.
    expect(await screen.findByRole("button", { name: "Reconnect" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Check connection" })).toBeEnabled();
  });

  it("explains that Instagram needs an image before you connect it", async () => {
    render(<SettingsPage />);
    expect(await screen.findByText(/requires an image/i)).toBeInTheDocument();
  });

  it("shows the destination once connected", async () => {
    mockFetchAccounts.mockResolvedValue([account()]);

    render(<SettingsPage />);

    expect(
      await screen.findByText("Western Riverina Community College"),
    ).toBeInTheDocument();
    expect(screen.getByText("Destination")).toBeInTheDocument();
    // The connect action becomes "Reconnect" rather than disappearing.
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("describes a Meta token as long-lived rather than inventing an expiry", async () => {
    mockFetchAccounts.mockResolvedValue([account({ token_expires_at: null })]);
    render(<SettingsPage />);
    expect(await screen.findByText(/no expiry/i)).toBeInTheDocument();
  });

  it("shows a plain valid-until date for a healthy LinkedIn token", async () => {
    mockFetchAccounts.mockResolvedValue([
      account({
        platform: "linkedin",
        display_name: "WRCC",
        token_expires_at: daysFromNow(45),
      }),
    ]);
    render(<SettingsPage />);
    expect(await screen.findByText(/Valid until/i)).toBeInTheDocument();
  });

  it("counts down when a token is close to expiring", async () => {
    mockFetchAccounts.mockResolvedValue([
      account({ platform: "linkedin", token_expires_at: daysFromNow(3) }),
    ]);

    render(<SettingsPage />);

    expect(await screen.findByText(/Expires in 3 days/i)).toBeInTheDocument();
  });

  it("tells the operator to reconnect once a token has expired", async () => {
    mockFetchAccounts.mockResolvedValue([
      account({
        platform: "linkedin",
        token_expires_at: daysFromNow(-1),
        token_expired: true,
      }),
    ]);

    render(<SettingsPage />);

    expect(
      await screen.findByText(/Connection expired — reconnect/i),
    ).toBeInTheDocument();
  });

  it("sends the browser to the provider when connecting", async () => {
    render(<SettingsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Connect Facebook" }));

    await waitFor(() => expect(mockAuthorizeUrl).toHaveBeenCalledWith("facebook"));
    expect(window.location.assign).toHaveBeenCalledWith(
      "https://facebook.test/dialog?state=abc",
    );
  });

  it("reports a failure to start the connection instead of navigating", async () => {
    mockAuthorizeUrl.mockRejectedValue(new Error("boom"));

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect Facebook" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not start the connection/i,
    );
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("switches the destination when another account is chosen", async () => {
    mockFetchAccounts.mockResolvedValue([
      account({ id: "a", display_name: "Page A", is_active: true }),
      account({
        id: "b",
        external_id: "page-2",
        display_name: "Page B",
        is_active: false,
      }),
    ]);

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Use this one" }));

    await waitFor(() => expect(mockActivate).toHaveBeenCalledWith("b"));
  });

  it("confirms before disconnecting, and keeping the account sends nothing", async () => {
    mockFetchAccounts.mockResolvedValue([account()]);

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));

    const dialog = screen.getByRole("dialog", {
      name: "Disconnect Western Riverina Community College?",
    });
    expect(dialog).toHaveTextContent("Posts already published stay live.");
    // The safe answer is the one that has focus.
    expect(within(dialog).getByRole("button", { name: "Keep connected" })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: "Keep connected" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockDisconnect).not.toHaveBeenCalled();
  });

  it("disconnects once confirmed", async () => {
    mockFetchAccounts.mockResolvedValue([account()]);

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );

    await waitFor(() => expect(mockDisconnect).toHaveBeenCalledWith("acct-1"));
  });

  it("surfaces the outcome the OAuth callback redirected back with", async () => {
    searchParams = new URLSearchParams("connected=meta");
    render(<SettingsPage />);
    expect(await screen.findByRole("status")).toHaveTextContent("Connected meta.");
  });

  it("surfaces an error the OAuth callback redirected back with", async () => {
    searchParams = new URLSearchParams(
      "error=That+connection+was+started+by+a+different+user.",
    );
    render(<SettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That connection was started by a different user.",
    );
  });

  it("reports a failure to load the account list", async () => {
    mockFetchAccounts.mockRejectedValue(new Error("network down"));
    render(<SettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not load connected accounts/i,
    );
  });
});

describe("Settings — checking a connection", () => {
  it("confirms a healthy connection", async () => {
    mockFetchAccounts.mockResolvedValue([account()]);
    mockVerify.mockResolvedValue({
      account: account(),
      ok: true,
      error: null,
      error_code: null,
    });

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Check connection" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /is connected and working/i,
    );
  });

  it("reports a dead token even though the request itself succeeded", async () => {
    // The endpoint returns 200 with ok:false — a dead token is information,
    // not a request error, so the UI must read `ok` rather than catch.
    mockFetchAccounts.mockResolvedValue([account()]);
    mockVerify.mockResolvedValue({
      account: account(),
      ok: false,
      error: "Session expired. Reconnect the account in Settings.",
      error_code: "reauth",
    });

    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Check connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Session expired/i);
  });
});
