import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { en } from "../src/app/lib/i18n/catalog-en";
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

/**
 * The section tabs of the analysis screen, by their accessible names.
 *
 * Derived from the catalogue rather than hand-listed, so a section added to `SECTIONS`
 * in `AnalysisTab` is covered as soon as its `analysis.tab*` label exists — which it
 * must, since a tab needs a label. The English catalogue specifically, because the
 * suite pins `locale: "en-GB"`.
 *
 * Deliberately no `data-testid`. There is not one in this repository: every locator
 * here goes through a role and an accessible name, which is what a reader and a screen
 * reader use, so a control that becomes unreachable by name fails a test rather than
 * quietly keeping its hook. Adding the first test-only attribute to production markup
 * to save three lines here would trade that away.
 */
function sectionNames(): string[] {
  return Object.entries(en)
    .filter(([key]) => key.startsWith("analysis.tab"))
    .map(([, label]) => label);
}

/**
 * Those actually present **in the analysis section nav**, so the loop is a no-op
 * everywhere else.
 *
 * Scoped to that `nav`, and it has to be: `/workouts` has its own button reading
 * "Strength", so an unscoped name match found it, clicked it, and then measured a
 * workouts screen while claiming to measure an analysis section. A locator that
 * matches the right words in the wrong place is worse than one that matches nothing.
 */
async function sectionTabs(page: Page): Promise<string[]> {
  const overview = page.getByRole("button", { name: sectionNames()[0], exact: true });
  if (!(await overview.count())) return [];
  const nav = page.locator("nav").filter({ has: overview });
  const present: string[] = [];
  for (const name of sectionNames()) {
    if (await nav.getByRole("button", { name, exact: true }).count()) present.push(name);
  }
  return present;
}

/**
 * The three measurable claims, in one place.
 *
 * The route body and the section loop have to make the *same* claim; two copies would
 * drift, and the copy that drifts is the one that stops failing.
 */
async function expectMeasurable(
  page: Page,
  what: string,
  theme: string,
  viewportName: string,
  viewport: { width: number; height: number },
) {
  const unresolvedMessages = await page.evaluate(() => {
    const attributes = Array.from(document.querySelectorAll<HTMLElement>("[aria-label], [title]"))
      .flatMap((element) => [element.getAttribute("aria-label"), element.getAttribute("title")])
      .filter((value): value is string => value !== null);
    const rendered = [document.body.innerText, ...attributes].join("\n");
    return Array.from(
      new Set(rendered.match(/\{[a-z][a-z0-9_]*\}|\banalysis\.[a-zA-Z0-9_.]+/g) ?? []),
    );
  });
  expect(
    unresolvedMessages,
    `filled ${what} renders unresolved message tokens (${theme}, ${viewportName}): ` +
      unresolvedMessages.join(", "),
  ).toEqual([]);

  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const fresh = scan.violations.filter(
    (violation) => !KNOWN_VIOLATIONS.has(violationKey(what, theme, violation.id)),
  );
  expect(
    fresh,
    `new accessibility violations on filled ${what} (${theme}, ${viewportName}):\n` +
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
    `filled ${what} overflows horizontally at ${viewport.width}px ` +
      `(scrollWidth ${overflow.scrollWidth} > ${overflow.clientWidth}); ` +
      `offenders: ${overflow.offenders.join(", ")}`,
  ).toEqual([]);

  const targets = await targetSizes(page);
  if (targets.under44.length > 0) {
    test.info().annotations.push({
      type: "under-44px",
      description: `filled ${what} (${viewport.width}px): ${targets.under44.join(", ")}`,
    });
  }
  expect(
    targets.tooSmall,
    `filled ${what} has controls below the WCAG 2.5.8 floor of 24x24 at ` +
      `${viewport.width}px: ${targets.tooSmall.join(", ")}`,
  ).toEqual([]);
}

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

          // Sections behind a tab are outside the document until the tab is clicked,
          // and on `/analysis` that is where all the dense content lives: the
          // correlation heatmap, the trend sparkline, the strength table, the outlier
          // list and the weekday chart. `expandCollapsedSections` above handles
          // `Disclosure`, which these are not — so the first pass measured the overview
          // and reported on the screen while six sevenths of it had never rendered.
          await expectMeasurable(page, route, theme, viewportName, viewport);

          // Each section measured and shot on its own, so a failure names the section
          // rather than the route.
          const sections = await sectionTabs(page);
          const sectionNav = sections.length
            ? page.locator("nav").filter({
                has: page.getByRole("button", { name: sections[0], exact: true }),
              })
            : null;
          for (const section of sections) {
            await sectionNav!.getByRole("button", { name: section, exact: true }).click();
            await settle(page);
            await expandCollapsedSections(page);
            if (SHOTS) {
              const slug = section.toLowerCase().replace(/[^a-z0-9]+/g, "-");
              await page.screenshot({
                path: `${SHOT_DIR}/${viewportName}-${theme}-analysis-${slug}.png`,
                fullPage: true,
              });
            }
            await expectMeasurable(page, `${route} > ${section}`, theme, viewportName, viewport);
          }
        });
      }
    });
  }
}
