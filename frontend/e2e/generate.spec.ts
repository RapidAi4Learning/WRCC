// The Generate button must be visible without scrolling on a laptop screen.
//
// The compose card used to be sticky and scroll its own fields, sized as if it
// were already stuck to the top of the window. When the form grew (the
// writing-speed selector) the button fell below the fold at 1440x900 — and at
// 1366x768 it already had. The form now flows with the page and the button is
// pinned to the window's bottom edge. `toBeInViewport` measures with
// IntersectionObserver, which also counts clipping by any scrolling ancestor.

import { expect, test } from "@playwright/test";

import { mockApi, signIn } from "./support/mockApi";
import { BASE_URL, choosePlatform } from "./support/screens";

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
]) {
  test.describe(`${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("the Generate button is fully visible on load", async ({ page }) => {
      await mockApi(page);
      await signIn(page, BASE_URL);
      await page.goto("/generate");

      await expect(
        page.getByRole("button", { name: /Generate 3 ideas/ }),
      ).toBeInViewport({ ratio: 1 });
    });

    test("every platform chip can still be ticked with the bar pinned", async ({ page }) => {
      await mockApi(page);
      await signIn(page, BASE_URL);
      await page.goto("/generate");

      // The pinned bar may sit over the chips on load; a person scrolls a
      // little and clicks — and so does choosePlatform.
      for (const name of ["Instagram", "LinkedIn"]) {
        await choosePlatform(page, name);
      }
    });
  });
}
