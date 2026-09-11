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

test("app icons and the web manifest are served without a session", async ({ request }) => {
  // The browser tab, the iOS home screen and the install prompt all fetch
  // these signed out; the login redirect must never answer them with HTML.
  const assets: Array<[string, string]> = [
    ["/icon.svg", "image/svg+xml"],
    ["/favicon.ico", "image/"],
    ["/apple-icon.png", "image/png"],
    ["/icons/icon-192.png", "image/png"],
    ["/icons/maskable-512.png", "image/png"],
    ["/manifest.webmanifest", "application/manifest+json"],
  ];
  for (const [path, type] of assets) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status(), path).toBe(200);
    expect(response.headers()["content-type"], path).toContain(type);
  }
});

test("settings is behind the login wall", async ({ page }) => {
  // The connections page lists which accounts posts publish to; it must not be
  // reachable without a session.
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings/);
});
