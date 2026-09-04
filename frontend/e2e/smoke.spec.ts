import { expect, test } from "@playwright/test";

test("login page renders", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("h1")).toHaveText("Social Media Marketing");
  await expect(page.getByLabel("Email")).toBeVisible();
  // Exact, because the reveal toggle beside it is labelled "Show password" and
  // a substring match resolves to both.
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("unauthenticated visitor is redirected to login", async ({ page }) => {
  await page.goto("/generate");
  await expect(page).toHaveURL(/\/login\?next=%2Fgenerate/);
});

test("root redirects to login when signed out", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});

test("settings is behind the login wall", async ({ page }) => {
  // The connections page lists which accounts posts publish to; it must not be
  // reachable without a session.
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings/);
});
