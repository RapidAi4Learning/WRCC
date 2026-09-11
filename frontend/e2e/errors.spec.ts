// What the person sees when the AI cannot finish a generation.
//
// The backend answers 503 with a readable `detail` when the AI fails or runs
// past its deadline (docs/GENERATION-LATENCY-PLAN.md). Before that fix the
// host killed the request and the screen could only say "Generation failed";
// this pins that the server's own message reaches the screen and that the
// form is usable again straight away.

import { expect, test } from "@playwright/test";

import { mockApi, signIn } from "./support/mockApi";
import { BASE_URL } from "./support/screens";

const TIMEOUT_DETAIL =
  "The AI took too long to answer. Try again, or generate for fewer platforms.";

test("a generation the AI cannot finish shows the server's message", async ({ page }) => {
  await mockApi(page);
  // Registered after mockApi, so it takes precedence for this one endpoint.
  await page.route("**/api/content/generate", (route) =>
    route.fulfill({ status: 503, json: { detail: TIMEOUT_DETAIL } }),
  );
  await signIn(page, BASE_URL);

  await page.goto("/generate");
  await page.locator("#topic").fill("Spring first aid enrolments in Griffith");
  const generate = page.getByRole("button", { name: /Generate 3 ideas/ });
  await generate.click();

  // Scoped to <main>: Next.js adds its own role="alert" route announcer to the
  // page, which would otherwise match as well.
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(TIMEOUT_DETAIL);
  // Nothing is stuck in "Generating…": the person can try again at once.
  await expect(generate).toBeEnabled();
  await expect(page.getByText("Your ideas land here")).toBeVisible();
});
