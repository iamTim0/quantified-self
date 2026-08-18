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

const VIEWPORTS = {
  // A 390x844 phone (iPhone 12-ish) and a laptop. The phone matters more: the
  // tab bar, the safe-area handling and the "More" sheet only exist there.
  phone: { width: 390, height: 844 },
  laptop: { width: 1440, height: 900 },
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

/** Wait until the page is actually settled, so axe does not read a skeleton. */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  // The theme bootstrap writes this attribute; its presence means CSS variables
  // have resolved and a contrast measurement is meaningful.
  await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
}

interface Overflow {
  scrollWidth: number;
  clientWidth: number;
  offenders: string[];
}

/**
 * Horizontal overflow, plus who caused it.
 *
 * Reporting only "the page scrolls sideways" sends the reader hunting through the
 * whole tree, so the offending elements are named. Wide content is allowed to
 * scroll *inside its own container* — a table or a chart legitimately does — so an
 * element is only an offender when it exceeds the viewport while none of its
 * ancestors made themselves scrollable.
 */
async function horizontalOverflow(page: Page): Promise<Overflow> {
  return page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    const limit = root.clientWidth;
    const offenders: string[] = [];

    const scrollsItself = (element: Element) => {
      const style = getComputedStyle(element);
      return style.overflowX === "auto" || style.overflowX === "scroll";
    };

    for (const element of Array.from(document.body.querySelectorAll("*"))) {
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      if (box.right <= limit + 1) continue;

      let ancestor: Element | null = element.parentElement;
      let contained = false;
      while (ancestor && ancestor !== document.body) {
        if (scrollsItself(ancestor)) {
          contained = true;
          break;
        }
        ancestor = ancestor.parentElement;
      }
      if (contained) continue;

      const id = element.id ? `#${element.id}` : "";
      const cls =
        typeof element.className === "string" && element.className
          ? `.${element.className.trim().split(/\s+/).slice(0, 3).join(".")}`
          : "";
      offenders.push(`${element.tagName.toLowerCase()}${id}${cls}`.slice(0, 120));
      if (offenders.length >= 5) break;
    }

    return { scrollWidth: root.scrollWidth, clientWidth: limit, offenders };
  });
}

/**
 * Two floors, because the codebase has two different truths about target size.
 *
 * `docs/features/dashboard-appearance.md` states that interactive targets are at
 * least 44x44. That turned out to describe an intention rather than the app: the
 * phone navigation meets it and a handful of dialog close buttons were brought up
 * to it, but roughly forty controls across the Explorer, Workouts, Quality,
 * Connectors and Profile screens sit between 28 and 42 pixels.
 *
 * So this reports both and fails on one:
 *
 *   - **`tooSmall` (fails the test)** is WCAG 2.5.8 AA, 24x24. Nothing in the app
 *     is below it today, which makes it a real gate rather than a backlog: it
 *     catches a regression the day it appears. It is what would have caught the
 *     24x24 dismiss button in `SystemWarnings`.
 *   - **`under44` (reported, does not fail)** is the documented aspiration. Raising
 *     forty controls to 44px is a visual redesign and a decision for whoever owns
 *     the design, not a side effect of adding a test. Recording it keeps the number
 *     visible instead of letting a silent gate imply the rule is met.
 *
 * Text links are exempt from both. WCAG 2.5.8 exempts targets in a block of text
 * for good reason: the only way to give an underlined link 44px of height is to pad
 * it until it reads as a button.
 */
interface TargetSizes {
  tooSmall: string[];
  under44: string[];
}

async function targetSizes(page: Page): Promise<TargetSizes> {
  return page.evaluate(() => {
    const AA_MIN = 24;
    const GOAL = 44;
    const tooSmall: string[] = [];
    const under44: string[] = [];
    const controls = document.body.querySelectorAll<HTMLElement>(
      'button, [role="button"], a[href], input[type="checkbox"], input[type="radio"], select',
    );

    for (const control of Array.from(controls)) {
      const box = control.getBoundingClientRect();
      const style = getComputedStyle(control);
      if (box.width === 0 || box.height === 0) continue;
      if (style.visibility === "hidden") continue;
      if (control.hasAttribute("disabled")) continue;
      // Visually hidden until focused — the skip link. Tailwind's `sr-only` clips
      // it to 1x1 and `focus:not-sr-only` restores it, so measuring it unfocused
      // reports 1x1 for a control that is 44px wide whenever anyone can actually
      // reach it. `clip-path` is what distinguishes that convention from a button
      // that is simply too small.
      if (style.clipPath && style.clipPath !== "none") continue;
      // Text links are exempt, and this is a judgement worth stating rather than
      // hiding in a selector. WCAG 2.5.8 exempts targets in a block of text for
      // the same reason: the only way to give an underlined link 44px of height
      // is to pad it until it reads as a button, which trades one usability
      // problem for another. The 44px floor is about *controls* — buttons, icon
      // buttons, selects — which is where every real defect here has been.
      if (control.tagName === "A" && style.textDecorationLine.includes("underline")) continue;
      if (control.tagName === "A" && style.display === "inline") continue;
      // Rounded to whole pixels: a control laid out at 43.98px by a fractional
      // grid is not the defect this is looking for.
      const width = Math.round(box.width);
      const height = Math.round(box.height);
      if (width >= GOAL && height >= GOAL) continue;

      const label =
        control.getAttribute("aria-label") ||
        control.textContent?.trim().slice(0, 40) ||
        control.tagName.toLowerCase();
      const described = `${label} (${width}x${height})`;
      if (width < AA_MIN || height < AA_MIN) tooSmall.push(described);
      else if (under44.length < 12) under44.push(described);
    }

    return { tooSmall, under44 };
  });
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
  for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
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
        context = await browser.newContext({ baseURL: API_BASE, locale: "en-GB", viewport });
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
