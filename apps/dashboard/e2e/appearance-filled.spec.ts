import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { KNOWN_VIOLATIONS, violationKey } from "./appearance-allowlist";
import { FILLED_ROUTES, useFixtures } from "./fixtures";
import { API_BASE, newAccount, signInAnyWidth, signUp } from "./helpers";
import { horizontalOverflow, settle, targetSizes } from "./appearance-checks";

/**
 * The same checks as `appearance.spec.ts`, on screens that actually hold data.
 *
 * That suite covers a fresh account, which means empty states — and it says so,
 * because an empty table cannot have a contrast fault in a cell it never renders.
 * This is the other half: workout cards, a chart with a series in it, a day story
 * with lanes and meals, a data-quality list with rows. The data comes from
 * `fixtures.ts` over intercepted requests; the page, the layout, the theme
 * bootstrap and the session are all real.
 *
 * `QS_SHOTS=1` also writes a screenshot per view, which is how a person or an agent
 * looks at the result rather than trusting a green tick. Off by default: CI does not
 * need the artefacts, and a suite that writes files on every run invites somebody to
 * commit them.
 */

/**
 * Open every collapsed section before measuring.
 *
 * The day story keeps its lanes, its event list and its meal log behind
 * `Disclosure`, closed by default — so a screenshot showed five collapsed headers
 * and axe scanned markup that was never in the document. The substance of the
 * screen was outside the test while the test reported on the screen.
 *
 * Clicking the page's own "Expand all" rather than forcing state, because that is
 * what a reader does, and a disclosure that fails to open is itself worth failing
 * on. Absent on screens that have none, hence the count check rather than a wait.
 */
async function expandCollapsedSections(page: Page) {
  const expandAll = page.getByRole("button", { name: /expand all/i });
  if ((await expandAll.count()) > 0) {
    await expandAll.first().click();
    // The sections mount on open; give the last one a frame to lay out before axe
    // measures contrast against a box that is still animating to its height.
    await page.waitForTimeout(400);
  }
}

/**
 * A phone is a touch device, and that is part of the fixture rather than a detail.
 *
 * A 390px viewport driven by a mouse reports `pointer: fine`, so every rule written
 * for thumbs is invisible to it — the suite would measure a layout no phone ever
 * renders and pass. `hasTouch` is what makes `@media (pointer: coarse)` true here.
 */
const VIEWPORTS = {
  phone: { viewport: { width: 390, height: 844 }, hasTouch: true },
  laptop: { viewport: { width: 1440, height: 900 }, hasTouch: false },
} as const;

const THEMES = ["light", "dark"] as const;

const SHOTS = process.env.QS_SHOTS === "1";
const SHOT_DIR = process.env.QS_SHOT_DIR ?? "/tmp/qs-filled";

for (const theme of THEMES) {
  for (const [viewportName, { viewport, hasTouch }] of Object.entries(VIEWPORTS)) {
    test.describe(`filled, ${theme} theme, ${viewportName}`, () => {
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
        });
        page = await context.newPage();
        await page.addInitScript(
          ([key, value]) => window.localStorage.setItem(key, value),
          ["qs-theme", theme],
        );
        // Before the first navigation, so no screen renders empty and then swaps.
        await useFixtures(page);
        await signInAnyWidth(page, account);
      });

      test.afterAll(async () => {
        await context?.close();
      });

      for (const route of FILLED_ROUTES) {
        test(`${route} holds up with data`, async () => {
          await page.goto(route);
          await settle(page);
          await expandCollapsedSections(page);

          if (SHOTS) {
            const name = route === "/" ? "overview" : route.replace(/\//g, "");
            await page.screenshot({
              path: `${SHOT_DIR}/${viewportName}-${theme}-${name}.png`,
              fullPage: true,
            });
          }

          const scan = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
            .analyze();
          const fresh = scan.violations.filter(
            (violation) => !KNOWN_VIOLATIONS.has(violationKey(route, theme, violation.id)),
          );
          expect(
            fresh,
            `new accessibility violations on filled ${route} (${theme}, ${viewportName}):\n` +
              fresh
                .map(
                  (v) =>
                    `  ${v.id} (${v.impact}): ${v.help}\n` +
                    v.nodes
                      .slice(0, 3)
                      .map((n) => `    ${n.target.join(" ")}`)
                      .join("\n"),
                )
                .join("\n"),
          ).toEqual([]);

          const overflow = await horizontalOverflow(page);
          expect(
            overflow.offenders,
            `filled ${route} overflows horizontally at ${viewport.width}px ` +
              `(scrollWidth ${overflow.scrollWidth} > ${overflow.clientWidth}); ` +
              `offenders: ${overflow.offenders.join(", ")}`,
          ).toEqual([]);

          const targets = await targetSizes(page);
          if (targets.under44.length > 0) {
            test.info().annotations.push({
              type: "under-44px",
              description: `filled ${route} (${viewport.width}px): ${targets.under44.join(", ")}`,
            });
          }
          expect(
            targets.tooSmall,
            `filled ${route} has controls below the WCAG 2.5.8 floor of 24x24 at ` +
              `${viewport.width}px: ${targets.tooSmall.join(", ")}`,
          ).toEqual([]);
        });
      }
    });
  }
}
