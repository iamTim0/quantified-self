import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { REPORT_ROUTES, useBrokenReportFixtures, useMinimalReportFixtures } from "./fixtures";
import { API_BASE, newAccount, signInAnyWidth, signUp } from "./helpers";

/**
 * Every screen that reads a precomputed report, handed a payload it does not know.
 *
 * `stale-reports.spec.ts` reproduces the outage that prompted all of this: the day
 * report gained `logged`, the overview called `story.logged.reduce(...)`, and every
 * existing installation showed a blank page after signing in. That test names the two
 * fields, which is right for a regression test and useless as a guarantee — the next
 * field to be added is not knowable today.
 *
 * This is the general form. `result: {}` is the lower bound of what a stored run can
 * return, so a tab that renders against it renders against every future rename too.
 * Reading the code first suggested `AnalysisTab` would fail here on seven separate
 * dereferences of fields typed as required; this suite is how that stops being a
 * reading and becomes a result.
 *
 * The assertion is `pageerror`, for the reason the earlier suite argues: the visible
 * symptom was Next's own error page, which no locator of ours describes, and
 * "the heading is present" passes on a page that already threw somewhere else.
 */

const VIEWPORT = { width: 1280, height: 900 };

test.describe("a stored report from another release", () => {
  let context: BrowserContext;
  let page: Page;
  const pageErrors = new Map<string, string[]>();
  let current = "";

  test.beforeAll(async ({ browser }) => {
    const api = await apiRequest.newContext({ baseURL: API_BASE });
    const account = newAccount();
    await signUp(api, account);
    await api.dispose();

    context = await browser.newContext({
      baseURL: API_BASE,
      locale: "en-GB",
      viewport: VIEWPORT,
    });
    page = await context.newPage();
    // Attributed to the route being visited, so a failure says which screen threw
    // rather than handing over one flat list for three of them.
    page.on("pageerror", (error) => {
      const errors = pageErrors.get(current) ?? [];
      errors.push(String(error).slice(0, 300));
      pageErrors.set(current, errors);
    });
    await useMinimalReportFixtures(page);
    await signInAnyWidth(page, account);
  });

  test.afterAll(async () => {
    await context?.close();
  });

  for (const route of REPORT_ROUTES) {
    test(`${route} renders against an unrecognised payload`, async () => {
      current = route;
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      // The throw happens during the render that follows the report, not during
      // the request, so waiting for the network to go quiet is not enough.
      await page.waitForTimeout(1500);

      const errors = pageErrors.get(route) ?? [];
      expect(
        errors,
        `${route} threw on a report payload it did not recognise:\n  ${errors.join("\n  ")}`,
      ).toEqual([]);

      // And the screen is actually there, rather than merely not having thrown.
      // `main` is the app shell; Next's fallback page has none.
      await expect(page.getByRole("main")).toBeVisible();
    });
  }
});

/**
 * And when a payload defeats normalisation anyway, the boundary catches it.
 *
 * Absence is answerable — `normaliseInsights` and `normaliseStory` answer it. A field
 * whose *type* changed is not, short of validating the whole payload on the client,
 * which this app does not do. So the second half of the answer is that a throw stops
 * at a boundary instead of taking the document with it.
 *
 * The assertion that matters is the last one: **the navigation is still there.** Next's
 * built-in fallback has none, so a reader whose analysis tab broke could not reach the
 * overview without editing the URL. That is the difference between one broken screen
 * and a dashboard that is down, and it is the whole reason the boundary sits inside the
 * `(dashboard)` group rather than at the app root.
 */
test.describe("a payload that throws anyway", () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    const api = await apiRequest.newContext({ baseURL: API_BASE });
    const account = newAccount();
    await signUp(api, account);
    await api.dispose();

    context = await browser.newContext({
      baseURL: API_BASE,
      locale: "en-GB",
      viewport: VIEWPORT,
    });
    page = await context.newPage();
    await useBrokenReportFixtures(page);
    await signInAnyWidth(page, account);
  });

  test.afterAll(async () => {
    await context?.close();
  });

  test("the reader gets a page they can act on, and keeps the navigation", async () => {
    await page.goto("/quality");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("alert").getByText("This screen stopped working")).toBeVisible();
    // Something to do, rather than a dead end.
    await expect(page.getByRole("button", { name: /try this screen again/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /reload the page/i })).toBeVisible();
    // The detail a bug report needs is present but not shouted.
    await expect(page.getByText("Technical detail")).toBeVisible();

    // The layout above the boundary survived, which is the point of where it sits.
    await expect(page.getByRole("navigation").first()).toBeVisible();
  });
});
