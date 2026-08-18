import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import AxeBuilder from "@axe-core/playwright";

import { KNOWN_VIOLATIONS, violationKey } from "./appearance-allowlist";
import { horizontalOverflow, settle, targetSizes } from "./appearance-checks";
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

/** As in the appearance suites: `hasTouch` is what makes `pointer: coarse` true. */
const VIEWPORTS = {
  phone: { viewport: { width: 390, height: 844 }, hasTouch: true },
  laptop: { viewport: { width: 1440, height: 900 }, hasTouch: false },
} as const;

const SHOTS = process.env.QS_SHOTS === "1";
const SHOT_DIR = process.env.QS_SHOT_DIR ?? "/tmp/qs-filled";

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
 * The crash screen is measured with the same checks as every other screen, in both
 * themes and at both widths, because it is a state nobody had ever looked at and the
 * one a reader meets at the worst possible moment. A dark-mode contrast fault or a
 * button under the tap-target floor is not more forgivable here than anywhere else —
 * it is less, because this is the screen someone is trying to get out of.
 */
for (const theme of ["light", "dark"] as const) {
  for (const [viewportName, { viewport, hasTouch }] of Object.entries(VIEWPORTS)) {
    test.describe(`a payload that throws anyway, ${theme}, ${viewportName}`, () => {
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
          viewport,
          hasTouch,
          // Contrast is measured on resolved colours, so nothing may be mid-transition
          // when axe runs. Clicking a section tab and measuring immediately caught the
          // button while `transition-colors` was interpolating, and axe reported
          // `#dee1e4` on `#36785c` — two blends that appear in no token file, failing at
          // 4.0:1 while the real pair (white on `#0d5c3a`) passes comfortably. A test
          // that invents a contrast defect is worse than one that misses a real one,
          // because somebody goes and "fixes" a correct colour.
          //
          // `reducedMotion` rather than a timeout: `globals.css` already collapses every
          // transition to 0.01ms under `prefers-reduced-motion`, so this is a mode the
          // app genuinely supports and every measurement becomes deterministic instead
          // of racing an animation. `expandCollapsedSections` keeps its wait — a
          // disclosure still needs a layout frame to reach its height.
          reducedMotion: "reduce",
        });
        page = await context.newPage();
        await page.addInitScript(
          ([key, value]) => window.localStorage.setItem(key, value),
          ["qs-theme", theme],
        );
        await useBrokenReportFixtures(page);
        await signInAnyWidth(page, account);
      });

      test.afterAll(async () => {
        await context?.close();
      });

      test("the reader gets a page they can act on, and keeps the navigation", async () => {
        await page.goto("/quality");
        await settle(page);

        await expect(
          page.getByRole("alert").getByText("This screen stopped working"),
        ).toBeVisible();
        // Something to do, rather than a dead end. Which of the three helps depends
        // on the cause, so all three are offered.
        await expect(page.getByRole("button", { name: /try this screen again/i })).toBeVisible();
        await expect(page.getByRole("button", { name: /reload the page/i })).toBeVisible();
        await expect(page.getByRole("link", { name: /back to the overview/i })).toBeVisible();
        // The detail a bug report needs is present but not shouted.
        await expect(page.getByText("Technical detail")).toBeVisible();

        // The layout above the boundary survived, which is the point of where it sits:
        // Next's own fallback has no navigation, so a reader whose screen broke could
        // not reach a working one without editing the URL.
        await expect(page.getByRole("navigation").first()).toBeVisible();

        if (SHOTS) {
          await page.screenshot({
            path: `${SHOT_DIR}/${viewportName}-${theme}-crash.png`,
            fullPage: true,
          });
        }

        // ── The same three measurements as every other screen ──────────────
        const scan = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        const fresh = scan.violations.filter(
          (violation) => !KNOWN_VIOLATIONS.has(violationKey("/crash", theme, violation.id)),
        );
        expect(
          fresh,
          `accessibility violations on the crash screen (${theme}, ${viewportName}):\n` +
            fresh.map((v) => `  ${v.id} (${v.impact}): ${v.help}`).join("\n"),
        ).toEqual([]);

        const overflow = await horizontalOverflow(page);
        expect(
          overflow.offenders,
          `the crash screen overflows horizontally at ${viewport.width}px; ` +
            `offenders: ${overflow.offenders.join(", ")}`,
        ).toEqual([]);

        const targets = await targetSizes(page);
        expect(
          targets.tooSmall,
          `the crash screen has controls below the WCAG 2.5.8 floor of 24x24 at ` +
            `${viewport.width}px: ${targets.tooSmall.join(", ")}`,
        ).toEqual([]);
      });
    });
  }
}
