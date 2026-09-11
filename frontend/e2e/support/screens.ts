// Every screen the UI specs look at, and how to get each one into the state
// worth looking at. Shared by the capture, layout/regression and accessibility
// specs so they always examine the same things.

import { expect, type Page } from "@playwright/test";

import { FIXED_NOW, mockApi, signIn } from "./mockApi";

export const BASE_URL = "http://localhost:3100";

export interface Screen {
  name: string;
  isSignedIn: boolean;
  /** Dialog screens are captured at viewport size; pages in full. */
  isFullPage: boolean;
  open: (page: Page) => Promise<void>;
}

/** Tick a platform chip the way a person does: by clicking the chip itself.
 *  Playwright then scrolls it into view and checks nothing covers it — the
 *  Generate bar is pinned to the window's bottom edge and can overlap it. */
export async function choosePlatform(page: Page, name: string): Promise<void> {
  const checkbox = page.getByRole("checkbox", { name });
  await page.locator("label").filter({ has: checkbox }).click();
  await expect(checkbox).toBeChecked();
}

async function openGenerated(page: Page) {
  await page.goto("/generate");
  await page.locator("#topic").fill("Spring first aid enrolments in Griffith");
  await choosePlatform(page, "Instagram");
  await page.getByRole("button", { name: /Generate 3 ideas/ }).click();
  await expect(page.getByText(/Spring is here/).first()).toBeVisible();
}

export const SCREENS: Screen[] = [
  {
    name: "01-login",
    isSignedIn: false,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    },
  },
  {
    name: "02-generate-empty",
    isSignedIn: true,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/generate");
      await expect(page.getByText("Your ideas land here")).toBeVisible();
    },
  },
  {
    name: "03-generate-results",
    isSignedIn: true,
    isFullPage: true,
    open: openGenerated,
  },
  {
    name: "04-media-panel",
    isSignedIn: true,
    isFullPage: false,
    open: async (page) => {
      await openGenerated(page);
      await page.getByRole("button", { name: /Media/ }).first().click();
      await expect(page.getByRole("dialog", { name: "Post media" })).toBeVisible();
      await expect(page.getByText(/trainer demonstrating CPR/)).toBeVisible();
    },
  },
  {
    name: "05-history",
    isSignedIn: true,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/history");
      await page.getByRole("button", { name: /Auslan for Beginners/ }).click();
      await expect(page.getByRole("link", { name: /View post/ })).toBeVisible();
    },
  },
  {
    name: "06-publish-dialog",
    isSignedIn: true,
    isFullPage: false,
    open: async (page) => {
      await page.goto("/history");
      await page
        .getByRole("button", { name: /Spring first aid/ })
        .filter({ hasText: "Approved" })
        .click();
      await page.getByRole("button", { name: "Preview" }).click();
      await expect(page.getByRole("dialog", { name: "Publish to Facebook" })).toBeVisible();
      await expect(page.getByText("Ready to publish.")).toBeVisible();
    },
  },
  {
    name: "07-catalog",
    isSignedIn: true,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/catalog");
      await expect(page.getByText("Awaiting your review")).toBeVisible();
      await page.getByRole("button", { name: /^HLTAID011/ }).click();
      await expect(page.getByText("Online + practical")).toBeVisible();
    },
  },
  {
    name: "08-settings",
    isSignedIn: true,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/settings");
      await expect(page.getByText("WRCC Company Page")).toBeVisible();
    },
  },
  {
    name: "09-ui-kit",
    isSignedIn: true,
    isFullPage: true,
    open: async (page) => {
      await page.goto("/ui-kit");
      await expect(page.getByRole("heading", { name: "UI kit" })).toBeVisible();
    },
  },
];

/** Fixed clock, canned API, and a session cookie when the screen needs one. */
export async function prepare(page: Page, screen: Screen): Promise<void> {
  await page.clock.setFixedTime(FIXED_NOW);
  await mockApi(page);
  if (screen.isSignedIn) await signIn(page, BASE_URL);
}

/** Pixels the page can be scrolled sideways — anything above 0 is a bug. */
export function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}
