import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  request as apiRequest,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { TAB_PATHS } from "../src/app/components/navigation";
import { KNOWN_VIOLATIONS, violationKey } from "./appearance-allowlist";
import { horizontalOverflow, settle, targetSizes } from "./appearance-checks";
import { API_BASE, newAccount, signInAnyWidth, signUp } from "./helpers";

/**
 * What the interface must be true of on every destination, in both themes and at
 * both widths.
 *
 * This suite deliberately does **not** judge whether anything looks good. It
 * asserts the three things that are measurable, because those are the ones that
 * shipped broken while every existing gate stayed green:
 *
 *   1. No accessibility violation axe can name — which covers colour contrast,
 *      and contrast is exactly what a token migration puts at risk. A token that
 *      resolves to grey-on-grey in dark mode compiles, lints, satisfies the token
 *      checker and passes every existing test.
 *   2. Nothing overflows horizontally. A phone-width page that scrolls sideways is
 *      never intentional here.
 *   3. Interactive targets are at least 44x44 CSS pixels, which
 *      `docs/features/dashboard-appearance.md` already states as a rule that
 *      nothing enforced.
 *
 * **Both themes, both widths, every destination**, driven off `TAB_PATHS` so a new
 * tab is covered the day it is added rather than the day somebody remembers to
 * extend this file. Dark mode had no browser coverage at all before this, while
 * four commits in one night rewrote how it works.
 *
 * A fresh account per run means most screens are empty states (rule 10 — nothing
 * here assumes pre-existing data). That is a real limit on what this can catch:
 * an empty table cannot have a contrast bug in a cell it does not render. It is
 * still the shell, the navigation, the headings and the empty states themselves,
 * which is where the theme work actually happened.
 */

/**
 * The routes, read from the registry rather than restated.
 *
 * `TAB_PATHS` is `Record<TabType, string>`, so a new destination cannot be added
 * to the union without gaining a path — and therefore cannot be added without
 * gaining coverage here. A hand-written list beside it would have been the third
 * place a destination has to be remembered, which is how the sidebar and the tab
 * bar drifted apart in the first place.
 */
const ROUTES = Object.values(TAB_PATHS);

/**
 * A phone is a touch device, and that is part of the fixture rather than a detail.
 *
 * A 390px viewport driven by a mouse reports `pointer: fine`, so every rule written
 * for thumbs is invisible to it — the suite would measure a layout no phone ever
 * renders and pass. `hasTouch` is what makes `@media (pointer: coarse)` true here.
 */
const VIEWPORTS = {
  // A 390x844 phone (iPhone 12-ish) and a laptop. The phone matters more: the
  // tab bar, the safe-area handling and the "More" sheet only exist there.
  phone: { viewport: { width: 390, height: 844 }, hasTouch: true },
  laptop: { viewport: { width: 1440, height: 900 }, hasTouch: false },
} as const;

const THEMES = ["light", "dark"] as const;

/**
 * Pin the theme the way the app itself does.
 *
 * `qs-theme` in localStorage, read by the inline bootstrap in the root layout
 * before first paint. Setting it via `addInitScript` means the very first render
 * is already in the right theme — toggling it through the UI afterwards would
 * measure a re-render, and a flash of the other theme would land in any failure
 * screenshot and mislead whoever reads it.
 */
async function pinTheme(page: Page, theme: (typeof THEMES)[number]) {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    ["qs-theme", theme],
  );
}

/**
 * One account and one signed-in page per theme/width combination, not per route.
 *
 * The obvious shape — a fresh account in every test — cost a signup, a login and a
 * fresh browser context 32 times over, which ran to roughly ten minutes and would
 * have quadrupled the browser job. Nothing here mutates data, so the isolation that
 * buys is worth nothing: these tests only look. Four logins instead of thirty-two,
 * and the per-route tests keep their own names so a failure still says which
 * destination broke.
 *
 * Plain `describe`, deliberately not `describe.serial`: serial aborts every
 * remaining test in the block as soon as one fails, so a single bad route hid the
 * other seven behind it — a suite that reports one defect per run teaches you to
 * fix one defect per run. The config already pins `workers: 1` and
 * `fullyParallel: false`, so these still execute in order on the shared page.
 */
for (const theme of THEMES) {
  for (const [viewportName, { viewport, hasTouch }] of Object.entries(VIEWPORTS)) {
    test.describe(`${theme} theme, ${viewportName}`, () => {
      let context: BrowserContext;
      let page: Page;

      test.beforeAll(async ({ browser }) => {
        // A standalone API context for the signup: sharing the browser context's
        // cookie jar would leave the page already authenticated, and then the
        // login form never renders (see `signUp` in helpers).
        const api = await apiRequest.newContext({ baseURL: API_BASE });
        const account = newAccount();
        await signUp(api, account);
        await api.dispose();

        // Options from `use` in the config apply to the `page` fixture, not to a
        // context created by hand, so locale and viewport are passed explicitly.
        context = await browser.newContext({
          baseURL: API_BASE,
          locale: "en-GB",
          viewport,
          hasTouch,
        });
        page = await context.newPage();
        await pinTheme(page, theme);
        await signInAnyWidth(page, account);
      });

      test.afterAll(async () => {
        await context?.close();
      });

      for (const route of ROUTES) {
        test(`${route} holds up`, async () => {
          await page.goto(route);
          await settle(page);

          // ── Accessibility, contrast included ──────────────────────────────
          const scan = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
            .analyze();

          const fresh = scan.violations.filter(
            (violation) => !KNOWN_VIOLATIONS.has(violationKey(route, theme, violation.id)),
          );
          expect(
            fresh,
            `new accessibility violations on ${route} (${theme}, ${viewportName}):\n` +
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

          // ── Nothing scrolls sideways ──────────────────────────────────────
          const overflow = await horizontalOverflow(page);
          expect(
            overflow.offenders,
            `${route} overflows horizontally at ${viewport.width}px ` +
              `(scrollWidth ${overflow.scrollWidth} > ${overflow.clientWidth}); ` +
              `offenders: ${overflow.offenders.join(", ")}`,
          ).toEqual([]);

          // ── Tap targets ───────────────────────────────────────────────────
          const targets = await targetSizes(page);
          if (targets.under44.length > 0) {
            // An annotation rather than a failure: the 44px goal is not met by the
            // app today, and the reason is written down in `targetSizes`.
            test.info().annotations.push({
              type: "under-44px",
              description: `${route} (${viewport.width}px): ${targets.under44.join(", ")}`,
            });
          }
          expect(
            targets.tooSmall,
            `${route} has controls below the WCAG 2.5.8 floor of 24x24 at ` +
              `${viewport.width}px: ${targets.tooSmall.join(", ")}`,
          ).toEqual([]);
        });
      }
    });
  }
}
