import { expect, type Page } from "@playwright/test";

/**
 * The measurable properties an interface has to hold, shared by the empty-state and
 * data-filled suites.
 *
 * Extracted rather than duplicated the moment there were two callers: a check that
 * exists twice drifts, and a drifted check is worse than a missing one because it
 * still reports green.
 */

/** Wait until the page is actually settled, so axe does not read a skeleton. */
export async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  // The theme bootstrap writes this attribute; its presence means CSS variables
  // have resolved and a contrast measurement is meaningful.
  await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
}

export interface Overflow {
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
export async function horizontalOverflow(page: Page): Promise<Overflow> {
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
export interface TargetSizes {
  tooSmall: string[];
  under44: string[];
}

export async function targetSizes(page: Page): Promise<TargetSizes> {
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
