import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { useStaleReportFixtures } from "./fixtures";
import { API_BASE, newAccount, signInAnyWidth, signUp } from "./helpers";

/**
 * The dashboard has to survive a report written by the version before it.
 *
 * This is not a hypothetical. A precomputed report is stored and served **while
 * stale** — `lib/reports.ts` argues for that deliberately, because a number with a
 * date on it beats recomputing on every page load. The consequence is that the first
 * client after a deploy reads payloads the previous release wrote, and every field the
 * new release added is missing from all of them.
 *
 * That took production down. `logged` and `logged_limit_reached` arrived with the meal
 * log; the overview did `story.logged.reduce(...)`, which on a payload from the day
 * before threw `Cannot read properties of undefined (reading 'reduce')`. React
 * unmounted the tree and Next rendered its built-in fallback, so signing in produced a
 * blank "This page couldn't load" for every existing installation — while the API
 * returned 200 for every call and every server log stayed clean.
 *
 * The assertion that matters is **`pageerror`**, not a visible string. The visible
 * symptom was Next's own error page, which no locator of ours describes, and asserting
 * "the heading is present" would have passed on a page that had already thrown once
 * elsewhere. An uncaught exception is the defect; everything else is downstream of it.
 */

const VIEWPORT = { width: 1280, height: 900 };

test.describe("a report written by an older release", () => {
  let context: BrowserContext;
  let page: Page;
  const pageErrors: string[] = [];

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
    page.on("pageerror", (error) => pageErrors.push(String(error).slice(0, 300)));
    await useStaleReportFixtures(page);
    await signInAnyWidth(page, account);
  });

  test.afterAll(async () => {
    await context?.close();
  });

  test("the overview renders instead of throwing", async () => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Long enough for the report to arrive and a render to follow it. The throw
    // happened during that render, not during the request.
    await page.waitForTimeout(1500);

    expect(
      pageErrors,
      `the overview threw on a report from an older release:\n  ${pageErrors.join("\n  ")}`,
    ).toEqual([]);

    // And the day actually rendered, rather than the page merely surviving empty.
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByText("What happened")).toBeVisible();
  });

  test("the sections that predate the payload are simply absent", async () => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);

    // The meal log is what the old payload has no data for. Absent is correct;
    // present-but-empty would be a section promising something it cannot show.
    await expect(page.getByText("Logged that day")).toHaveCount(0);
    // The lanes it *does* carry are unaffected, which is the point of tolerating a
    // partial payload rather than rejecting the whole report.
    await expect(page.getByText("Sleep", { exact: true })).toBeVisible();
    expect(pageErrors, pageErrors.join("\n")).toEqual([]);
  });
});
